/**
 * One Ask conversation with a company's brain: its turns, the live run and the replay.
 *
 * Why: a question is one streamed request (POST .../ask, see api/ask.ts) whose events arrive over
 * seconds: each tool call is asked for, then done, then the answer comes. This class turns those
 * events into turns the page draws, keeps the thread id so follow-ups join the same conversation,
 * and owns Stop (aborting the request; the server then stops the run at its next step) and Replay
 * (showing a finished walk again, one step at a time). A thumbs up or down on an answer is saved on
 * its trace (`rate`); thumbs-down answers become draft eval cases on the server. Each Claude
 * response arrives as an `llm` event and is kept on its turn (`calls`), with the tools it asked
 * for, so the page can show what Claude said and called. The server keeps every chat; `load`
 * reopens one (`turnFromChat` turns the saved shape back into turns).
 */
import { postEvents } from './api/ask';
import { api, describeError } from './api/client';
import type {
	AskAnswer,
	AskCall,
	AskLlmEvent,
	AskStepDoneEvent,
	AskStepEvent,
	ChatTurn,
	Rating,
	WalkStep
} from './types';

export const REPLAY_STEP_MS = 700;

export interface Turn {
	question: string;
	/** The model id this question asked for (null: the server's default). Answers name the one that served. */
	model: string | null;
	/** Claude's responses in order, each with the tools it asked for. */
	calls: AskLlmEvent[];
	/** The graph steps and answer checks (the walk). MCP and server calls stay on `calls`. */
	steps: WalkStep[];
	answer: AskAnswer | null;
	error: string | null;
	status: 'running' | 'done' | 'failed' | 'stopped';
	/** The thumbs on the answer, as saved (or being saved). */
	rating: Rating | null;
	/** What was wrong, sent with a thumbs down. */
	note: string | null;
	/** The last save: `failed` keeps the rating that was there before. */
	rated: 'idle' | 'saving' | 'saved' | 'failed';
}

const EXAMPLES = [
	'Who works most closely with whom?',
	'Which systems usually change together?',
	'Where do the declared owners differ from who does the work?'
];

export const NOT_RUN = 'Not run: the answer ended before this call.';

/** A turn is over: any call still shown as running never will run. */
function endSteps(turn: Turn): void {
	for (const s of turn.steps) {
		if (s.status !== 'running') continue;
		s.status = 'done';
		s.error = NOT_RUN;
	}
}

/** A saved turn (GET .../threads/{id}) as the page draws it. */
export function turnFromChat(t: ChatTurn): Turn {
	const walk = t.steps.filter((s) => s.kind === 'graph' || s.kind === 'submit');
	const asked = (seq: number): AskCall[] =>
		t.steps
			.filter((s) => s.call === seq)
			.map((s) => ({
				id: s.id,
				tool: s.tool,
				kind: s.kind,
				server: s.server,
				input: s.input ?? {},
				error: s.error,
				result: s.result
			}));
	const turn: Turn = {
		question: t.question,
		model: t.answer?.model ?? t.calls.at(-1)?.model ?? null,
		calls: t.calls.map((c) => ({ ...c, calls: asked(c.seq) })),
		steps: walk.map((s) => ({
			id: s.id,
			n: s.n,
			tool: s.tool,
			input: s.input,
			call: s.call,
			status: s.status === 'running' ? 'running' : 'done',
			ms: s.ms,
			count: s.count,
			error: s.error,
			rows: s.rows,
			nodes: s.nodes,
			rels: s.rels
		})),
		answer: t.answer,
		error: t.error,
		status: t.status,
		rating: t.rating,
		note: t.note,
		rated: 'idle'
	};
	if (turn.status !== 'running') endSteps(turn);
	return turn;
}

export class AskThread {
	turns = $state<Turn[]>([]);
	threadId = $state<string | null>(null);
	/** The turn whose walk the stage shows. */
	selected = $state(0);
	/** While replaying: how many graph steps are shown; null shows them all. */
	revealed = $state<number | null>(null);
	/** Reopening a saved chat (`load`). */
	loading = $state(false);
	loadError = $state<string | null>(null);
	readonly examples = EXAMPLES;

	#abort: AbortController | null = null;
	#timer: ReturnType<typeof setInterval> | null = null;
	#loadToken = 0;

	/**
	 * @param onstart called when a question gets its thread id (a new chat is saved from then on)
	 * @param onend called when a question ends, however it ended
	 */
	constructor(
		readonly slug: string,
		readonly onstart?: (threadId: string) => void,
		readonly onend?: (threadId: string | null) => void
	) {}

	get running(): boolean {
		return this.turns.some((t) => t.status === 'running');
	}

	/**
	 * Ask a question; a follow-up when the thread already has turns. `model` picks the Claude model
	 * for this question only (GET /api/models); null or omitted runs on the server's default.
	 */
	async ask(question: string, model: string | null = null): Promise<void> {
		const text = question.trim();
		if (!text || this.running) return;
		this.#stopReplay();
		this.turns.push({
			question: text,
			model,
			calls: [],
			steps: [],
			answer: null,
			error: null,
			status: 'running',
			rating: null,
			note: null,
			rated: 'idle'
		});
		const index = this.turns.length - 1;
		const turn = this.turns[index];
		this.selected = index;
		const abort = new AbortController();
		this.#abort = abort;
		const body = {
			question: text,
			...(this.threadId ? { thread_id: this.threadId } : {}),
			...(model ? { model } : {})
		};
		try {
			await postEvents(
				`/companies/${encodeURIComponent(this.slug)}/ask`,
				body,
				(event, data) => this.#apply(turn, event, data),
				abort.signal
			);
			if (turn.status === 'running') {
				turn.status = 'failed';
				turn.error = 'The answer stopped before it finished. Ask again.';
			}
		} catch (e) {
			if (abort.signal.aborted) {
				turn.status = 'stopped';
			} else {
				turn.status = 'failed';
				turn.error = describeError(e);
			}
		} finally {
			if (this.#abort === abort) this.#abort = null;
			endSteps(turn);
			this.onend?.(this.threadId);
		}
	}

	#apply(turn: Turn, event: string, data: unknown): void {
		if (event === 'start') {
			this.threadId = (data as { thread_id: string }).thread_id;
			this.onstart?.(this.threadId);
		} else if (event === 'llm') {
			const call = data as AskLlmEvent;
			if (!turn.calls.some((c) => c.seq === call.seq)) turn.calls.push(call);
		} else if (event === 'step') {
			const step = data as AskStepEvent;
			if (!turn.steps.some((s) => s.id === step.id)) turn.steps.push({ ...step, status: 'running' });
		} else if (event === 'step_done') {
			const done = { ...(data as AskStepDoneEvent), status: 'done' as const };
			const at = turn.steps.findIndex((s) => s.id === done.id);
			if (at === -1) turn.steps.push(done);
			else turn.steps[at] = done;
		} else if (event === 'answer') {
			const answer = data as AskAnswer;
			turn.answer = answer;
			this.threadId = answer.thread_id;
			turn.status = answer.stop === 'stopped' ? 'stopped' : 'done';
		} else if (event === 'error') {
			turn.error = (data as { detail: string }).detail;
			turn.status = 'failed';
		}
	}

	/**
	 * Rate a turn's answer (null takes the thumbs back). The thumbs moves at once; a failed save
	 * puts the previous one back and says so. Answers without a trace cannot be rated.
	 */
	async rate(index: number, rating: Rating | null, note?: string): Promise<void> {
		const turn = this.turns[index];
		const traceId = turn?.answer?.trace_id;
		if (!turn || !traceId || turn.rated === 'saving') return;
		const before = { rating: turn.rating, note: turn.note };
		turn.rating = rating;
		if (note !== undefined) turn.note = note.trim() || null;
		turn.rated = 'saving';
		try {
			const saved = await api.feedback(this.slug, traceId, rating, rating === 'down' ? (turn.note ?? undefined) : undefined);
			turn.rating = saved.rating;
			turn.note = saved.note;
			turn.rated = 'saved';
		} catch {
			turn.rating = before.rating;
			turn.note = before.note;
			turn.rated = 'failed';
		}
	}

	/** Stop the running answer. */
	stop(): void {
		this.#abort?.abort();
	}

	/** Start a new conversation (stops a running one). */
	reset(): void {
		this.stop();
		this.#stopReplay();
		this.turns = [];
		this.threadId = null;
		this.selected = 0;
		this.loadError = null;
		this.loading = false;
		this.#loadToken++;
	}

	/**
	 * Reopen a saved chat: its turns replace the current ones, and the next question follows it up.
	 * A load that a newer load or reset overtook is dropped.
	 */
	async load(id: string): Promise<void> {
		if (id === this.threadId && this.turns.length) return;
		this.reset();
		const token = this.#loadToken;
		this.threadId = id;
		this.loading = true;
		try {
			const thread = await api.thread(this.slug, id);
			if (token !== this.#loadToken) return;
			this.turns = thread.turns.map(turnFromChat);
			this.selected = Math.max(0, this.turns.length - 1);
		} catch (e) {
			if (token !== this.#loadToken) return;
			this.threadId = null;
			this.loadError = describeError(e);
		} finally {
			if (token === this.#loadToken) this.loading = false;
		}
	}

	/** Show a turn's walk on the stage. */
	select(index: number): void {
		if (index === this.selected) return;
		this.#stopReplay();
		this.selected = index;
	}

	/** Show the selected turn's walk again, a step at a time (all at once under reduced motion). */
	replay(reducedMotion = false): void {
		this.#stopReplay();
		const total = this.turns[this.selected]?.steps.filter((s) => s.n !== null).length ?? 0;
		if (reducedMotion || total === 0) return;
		this.revealed = 0;
		this.#timer = setInterval(() => {
			const next = (this.revealed ?? total) + 1;
			if (next >= total) this.#stopReplay();
			else this.revealed = next;
		}, REPLAY_STEP_MS);
	}

	get replaying(): boolean {
		return this.revealed !== null;
	}

	#stopReplay(): void {
		if (this.#timer !== null) clearInterval(this.#timer);
		this.#timer = null;
		this.revealed = null;
	}

	/** Leave the page: stop the run and the replay. */
	dispose(): void {
		this.stop();
		this.#stopReplay();
	}
}
