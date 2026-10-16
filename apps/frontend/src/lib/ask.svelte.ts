/**
 * One Ask conversation with a company's brain: its turns, the live run and the replay.
 *
 * Why: a question is one streamed request (POST .../ask, see api/ask.ts) whose events arrive over
 * seconds: each tool call is asked for, then done, then the answer comes. This class turns those
 * events into turns the page draws, keeps the thread id so follow-ups join the same conversation,
 * and owns Stop (aborting the request; the server then stops the run at its next step) and Replay
 * (showing a finished walk again, one step at a time). A thumbs up or down on an answer is saved on
 * its trace (`rate`); thumbs-down answers become draft eval cases on the server.
 */
import { postEvents } from './api/ask';
import { api, describeError } from './api/client';
import type { AskAnswer, AskStepDoneEvent, AskStepEvent, Rating, WalkStep } from './types';

export const REPLAY_STEP_MS = 700;

export interface Turn {
	question: string;
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

export class AskThread {
	turns = $state<Turn[]>([]);
	threadId = $state<string | null>(null);
	/** The turn whose walk the stage shows. */
	selected = $state(0);
	/** While replaying: how many graph steps are shown; null shows them all. */
	revealed = $state<number | null>(null);
	readonly examples = EXAMPLES;

	#abort: AbortController | null = null;
	#timer: ReturnType<typeof setInterval> | null = null;

	constructor(readonly slug: string) {}

	get running(): boolean {
		return this.turns.some((t) => t.status === 'running');
	}

	/** Ask a question; a follow-up when the thread already has turns. */
	async ask(question: string): Promise<void> {
		const text = question.trim();
		if (!text || this.running) return;
		this.#stopReplay();
		this.turns.push({
			question: text,
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
		const body = this.threadId ? { question: text, thread_id: this.threadId } : { question: text };
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
		}
	}

	#apply(turn: Turn, event: string, data: unknown): void {
		if (event === 'start') {
			this.threadId = (data as { thread_id: string }).thread_id;
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
