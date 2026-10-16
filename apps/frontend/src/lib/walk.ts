/**
 * The agent's walk through the graph, as the Ask page draws it (design direction D).
 *
 * Why: each tool call arrives with the nodes and relationships it touched (brain/agents/walk.py).
 * This module merges the steps of one answer into one picture, lays it out so earlier nodes stay
 * put as new steps arrive, works out what a citation lights up, and turns rows, calls and the
 * answer's Markdown into plain values the components render. Pure: no Svelte, no fetch.
 */
import type { AskSource, NodeType, WalkNode, WalkRel, WalkStep } from './types';

const TYPES: Record<string, NodeType> = {
	Person: 'person',
	Team: 'team',
	System: 'system',
	WorkItem: 'work-item',
	Change: 'change',
	Document: 'document'
};

/** The UI's node type for a graph label (unknown labels draw as documents: grey). */
export function nodeType(label: string | null | undefined): NodeType {
	return (label && TYPES[label]) || 'document';
}

export const relKey = (r: Pick<WalkRel, 'from' | 'to' | 'type'>) => `${r.from}|${r.type}|${r.to}`;

export interface MergedNode extends WalkNode {
	/** The step that first touched it. */
	step: number;
}
export interface MergedRel extends WalkRel {
	step: number;
	key: string;
}
export interface Walk {
	nodes: MergedNode[];
	rels: MergedRel[];
	/** The node the walk starts from: drawn in ink at the centre. */
	focus: string | null;
}

/** The graph steps (not the answer check) merged in order; each node and link keeps its first step. */
export function mergeWalk(steps: WalkStep[]): Walk {
	const nodes = new Map<string, MergedNode>();
	const rels = new Map<string, MergedRel>();
	let focus: string | null = null;
	for (const s of steps) {
		if (s.n === null) continue;
		for (const n of s.nodes ?? []) {
			focus ??= n.uid;
			if (!nodes.has(n.uid)) nodes.set(n.uid, { ...n, step: s.n });
		}
		for (const r of s.rels ?? []) {
			const key = relKey(r);
			if (!rels.has(key)) rels.set(key, { ...r, step: s.n, key });
		}
	}
	return { nodes: [...nodes.values()], rels: [...rels.values()], focus };
}

// --- layout -------------------------------------------------------------------------------

export interface Point {
	x: number;
	y: number;
}

/** The stage's coordinate space; the component scales it to its box. */
export const STAGE = { width: 640, height: 420 } as const;
const MARGIN_X = 104; // node pills are wide: keep their centres this far from the sides
const MARGIN_Y = 26;
const SQUASH = 2; // lay out in a space this much narrower, so pills repel more sideways
const ITERATIONS = 180;

function hash(s: string): number {
	let h = 2166136261;
	for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
	return (h >>> 0) / 4294967296;
}

/**
 * Positions for every node. Deterministic. Nodes in `prev` start where they were and move little,
 * so a new step adds to the picture instead of reshuffling it; new nodes start beside a neighbour.
 * `halfWidth` says how wide each node is drawn (see `pillHalfWidth`), so names never overlap.
 */
export function layoutWalk(
	walk: Walk,
	prev: ReadonlyMap<string, Point> = new Map(),
	halfWidth: (uid: string) => number = (uid) => pillHalfWidth(walk.nodes.find((n) => n.uid === uid)?.title ?? '')
): Map<string, Point> {
	const W = STAGE.width / SQUASH;
	const H = STAGE.height;
	const cx = W / 2;
	const cy = H / 2;
	const minX = MARGIN_X / SQUASH;
	const maxX = W - minX;
	const clampX = (x: number) => Math.min(maxX, Math.max(minX, x));
	const clampY = (y: number) => Math.min(H - MARGIN_Y, Math.max(MARGIN_Y, y));

	const pos = new Map<string, Point>();
	const old = new Set<string>();
	const neighbours = new Map<string, string[]>();
	for (const r of walk.rels) {
		neighbours.set(r.from, [...(neighbours.get(r.from) ?? []), r.to]);
		neighbours.set(r.to, [...(neighbours.get(r.to) ?? []), r.from]);
	}
	walk.nodes.forEach((n, i) => {
		const p = prev.get(n.uid);
		if (p) {
			pos.set(n.uid, { x: p.x / SQUASH, y: p.y });
			old.add(n.uid);
			return;
		}
		if (n.uid === walk.focus) {
			pos.set(n.uid, { x: cx, y: cy });
			return;
		}
		const angle = hash(n.uid) * Math.PI * 2;
		const anchor = (neighbours.get(n.uid) ?? []).map((u) => pos.get(u)).find(Boolean);
		const base = anchor ?? { x: cx, y: cy };
		const r = anchor ? 110 : 90 + (i % 5) * 18;
		pos.set(n.uid, { x: clampX(base.x + Math.cos(angle) * r / SQUASH), y: clampY(base.y + Math.sin(angle) * r) });
	});

	const ids = walk.nodes.map((n) => n.uid);
	const start = new Map([...old].map((u) => [u, { ...pos.get(u)! }]));
	const k =Math.sqrt((W * H) / Math.max(ids.length, 1)) * 0.85;
	for (let it = 0; it < ITERATIONS; it++) {
		const temp = (W / 8) * (1 - it / ITERATIONS) + 0.5;
		const disp = new Map<string, Point>(ids.map((u) => [u, { x: 0, y: 0 }]));
		for (let i = 0; i < ids.length; i++) {
			for (let j = i + 1; j < ids.length; j++) {
				const a = pos.get(ids[i])!;
				const b = pos.get(ids[j])!;
				let dx = a.x - b.x;
				let dy = a.y - b.y;
				let d = Math.hypot(dx, dy);
				if (d < 0.01) {
					dx = hash(ids[i] + ids[j]) - 0.5;
					dy = 0.5;
					d = Math.hypot(dx, dy);
				}
				const f = (k * k) / d;
				const da = disp.get(ids[i])!;
				const db = disp.get(ids[j])!;
				da.x += (dx / d) * f;
				da.y += (dy / d) * f;
				db.x -= (dx / d) * f;
				db.y -= (dy / d) * f;
			}
		}
		for (const r of walk.rels) {
			const a = pos.get(r.from);
			const b = pos.get(r.to);
			if (!a || !b) continue;
			const dx = a.x - b.x;
			const dy = a.y - b.y;
			const d = Math.max(Math.hypot(dx, dy), 0.01);
			const f = (d * d) / k;
			const da = disp.get(r.from)!;
			const db = disp.get(r.to)!;
			da.x -= (dx / d) * f;
			da.y -= (dy / d) * f;
			db.x += (dx / d) * f;
			db.y += (dy / d) * f;
		}
		for (const u of ids) {
			if (u === walk.focus) continue; // the start stays in the middle
			const p = pos.get(u)!;
			const v = disp.get(u)!;
			v.x += (cx - p.x) * GRAVITY * k; // a little gravity keeps islands on stage
			v.y += (cy - p.y) * GRAVITY * k;
			const len = Math.max(Math.hypot(v.x, v.y), 0.01);
			const step = Math.min(len, old.has(u) ? temp * 0.2 : temp);
			p.x = clampX(p.x + (v.x / len) * step);
			p.y = clampY(p.y + (v.y / len) * step);
			const from = start.get(u);
			if (from) {
				// A node already drawn may drift only a little from where the reader saw it.
				const dx = (p.x - from.x) * SQUASH;
				const dy = p.y - from.y;
				const drift = Math.hypot(dx, dy);
				if (drift > MAX_DRIFT) {
					p.x = from.x + ((dx / drift) * MAX_DRIFT) / SQUASH;
					p.y = from.y + (dy / drift) * MAX_DRIFT;
				}
			}
		}
	}
	const out = new Map([...pos].map(([u, p]) => [u, { x: p.x * SQUASH, y: p.y }]));
	separate(out, walk.focus, old, halfWidth);
	return out;
}

const GRAVITY = 0.004;
const MAX_DRIFT = 36; // stage units a drawn node may move when a step adds to the walk
const NODE_HALF_HEIGHT = 15;
const GAP = 6;

/**
 * Push apart nodes whose boxes overlap, along the axis that needs the smaller move. Forces work on
 * centres; pills are wide, so this last pass is what keeps two names from printing on each other.
 */
function separate(
	pos: Map<string, Point>,
	focus: string | null,
	old: ReadonlySet<string>,
	halfWidth: (uid: string) => number
) {
	const ids = [...pos.keys()];
	const weight = (u: string) => (u === focus ? 0 : old.has(u) ? 0.15 : 1);
	const clamp = (u: string, p: Point) => {
		const hw = halfWidth(u) + GAP;
		p.x = Math.min(STAGE.width - hw, Math.max(hw, p.x));
		p.y = Math.min(STAGE.height - MARGIN_Y, Math.max(MARGIN_Y, p.y));
	};
	for (let round = 0; round < 60; round++) {
		let moved = false;
		for (let i = 0; i < ids.length; i++) {
			for (let j = i + 1; j < ids.length; j++) {
				const a = pos.get(ids[i])!;
				const b = pos.get(ids[j])!;
				const dx = b.x - a.x;
				const dy = b.y - a.y;
				const ox = halfWidth(ids[i]) + halfWidth(ids[j]) + GAP - Math.abs(dx);
				const oy = NODE_HALF_HEIGHT * 2 + GAP - Math.abs(dy);
				if (ox <= 0 || oy <= 0) continue;
				moved = true;
				const alongY = oy <= ox;
				const sign = (alongY ? dy : dx) >= 0 ? 1 : -1;
				const amount = alongY ? oy : ox;
				// The start never moves; nodes already drawn give way less than new ones.
				const wa = weight(ids[i]);
				const wb = weight(ids[j]);
				const shareA = wa + wb === 0 ? 0.5 : wa / (wa + wb);
				const shareB = 1 - shareA;
				if (alongY) {
					a.y -= sign * amount * shareA;
					b.y += sign * amount * shareB;
				} else {
					a.x -= sign * amount * shareA;
					b.x += sign * amount * shareB;
				}
				clamp(ids[i], a);
				clamp(ids[j], b);
			}
		}
		if (!moved) break;
	}
}

/** Half the width of a node's pill in stage units, from its name: what `separate` keeps apart. */
export function pillHalfWidth(title: string | null, maxChars = 26): number {
	if (title === null) return 8; // a dot
	return (Math.min(title.length, maxChars) * 7 + 34) / 2;
}

// --- what a citation lights up -----------------------------------------------------------

export interface Highlight {
	nodes: Set<string>;
	rels: Set<string>;
}

interface PathRow {
	nodes?: { uid: string }[];
	rels?: { type: string; from: string; to: string }[];
}

/** The node a call was about, when it names one: get_entity's uid, a profile's person, a system. */
export function subjectOf(step: Pick<WalkStep, 'tool' | 'input'>): string | null {
	const p = step.input ?? {};
	if (step.tool === 'get_entity' && typeof p.uid === 'string') return p.uid;
	if (step.tool === 'person_profile' && typeof p.login === 'string') return `person:${p.login.toLowerCase()}`;
	if (['experts_for_system', 'work_history', 'impact_of'].includes(step.tool) && typeof p.system === 'string')
		return `system:${p.system}`;
	return null;
}

/** More links than this from "about it" steps is a hub: they would light everything. */
const SUBJECT_LINKS_MAX = 10;

/**
 * The part of the walk that backs a cited node: in the step that first returned it, the paths
 * (from path_between) that run through it, else its own links in that step; plus its links from
 * steps that were about it (opening a PR adds who wrote it), unless that makes it a hub. Never
 * the whole merged graph: a team or system is linked to almost everything.
 */
export function highlightFor(source: Pick<AskSource, 'uid' | 'step'>, steps: WalkStep[]): Highlight {
	const { uid } = source;
	const nodes = new Set([uid]);
	const rels = new Set<string>();
	const step =
		steps.find((s) => s.n !== null && s.n === source.step) ??
		steps.find((s) => s.n !== null && (s.nodes ?? []).some((n) => n.uid === uid));
	if (!step) return { nodes, rels };
	const touching = (s: WalkStep) => (s.rels ?? []).filter((r) => r.from === uid || r.to === uid);
	const light = (rs: WalkRel[]) => {
		for (const r of rs) {
			rels.add(relKey(r));
			nodes.add(r.from);
			nodes.add(r.to);
		}
	};
	if (step.tool === 'path_between') {
		const through = ((step.rows ?? []) as PathRow[]).filter((r) => r.nodes?.some((n) => n.uid === uid));
		for (const row of through) {
			row.nodes?.forEach((n) => nodes.add(n.uid));
			row.rels?.forEach((r) => rels.add(relKey(r)));
		}
		if (through.length) return { nodes, rels };
	}
	light(touching(step));
	const about = steps.filter((s) => s !== step && s.n !== null && subjectOf(s) === uid).flatMap(touching);
	if (about.length <= SUBJECT_LINKS_MAX) light(about);
	return { nodes, rels };
}

// --- words for steps and rows ------------------------------------------------------------

/** A uid as a person reads it: person:alice -> alice, x:pr:10 -> PR #10. */
export function shortUid(uid: string): string {
	const parts = uid.split(':');
	const [kind, id] = parts.slice(-2);
	if (parts.length >= 3 && kind === 'pr') return `PR #${id}`;
	if (parts.length >= 3 && kind === 'issue') return `issue #${id}`;
	if (parts.length >= 3 && kind === 'commit') return `commit ${id}`;
	return parts.slice(1).join(':') || uid;
}

const str = (v: unknown) => (typeof v === 'string' ? v : v === undefined || v === null ? '' : String(v));

type Said = [now: string, done: string];
/** Each tool's sentence while it runs and once it is done; `p` is the call's input. */
const SAID: Record<string, (p: Record<string, unknown>) => Said> = {
	person_profile: (p) => [`Looking up ${str(p.login)}'s profile`, `Looked up ${str(p.login)}'s profile`],
	experts_for_system: (p) => [`Asking who knows ${str(p.system)} best`, `Asked who knows ${str(p.system)} best`],
	path_between: (p) => {
		const pair = `${shortUid(str(p.from_uid))} and ${shortUid(str(p.to_uid))}`;
		return [`Finding how ${pair} connect`, `Found how ${pair} connect`];
	},
	work_history: (p) => [`Reading recent work on ${str(p.system)}`, `Read recent work on ${str(p.system)}`],
	impact_of: (p) => [`Checking what changes together with ${str(p.system)}`, `Checked what changes together with ${str(p.system)}`],
	related_work_items: (p) => [`Searching PRs and issues for "${str(p.text)}"`, `Searched PRs and issues for "${str(p.text)}"`],
	related_documents: (p) => [`Searching docs for "${str(p.text)}"`, `Searched docs for "${str(p.text)}"`],
	get_entity: (p) => [`Opening ${shortUid(str(p.uid))}`, `Opened ${shortUid(str(p.uid))}`],
	list_systems: () => ['Listing the systems', 'Listed the systems'],
	owners_vs_experts: () => ['Comparing declared owners with who does the work', 'Compared declared owners with who does the work'],
	recent_work_items: () => ['Reading the latest work', 'Read the latest work'],
	people_activity: () => ['Listing people and their activity', 'Listed people and their activity'],
	graph_stats: () => ['Counting what the graph holds', 'Counted what the graph holds'],
	submit_answer: () => ['Checking the answer against what was found', 'Checked the answer against what was found']
};

/** What the agent is doing in this step, in plain words; `done` says what it did. */
export function stepSentence(step: Pick<WalkStep, 'tool' | 'input'>, done = false): string {
	const said = SAID[step.tool]?.(step.input ?? {}) ?? [`Running ${step.tool}`, `Ran ${step.tool}`];
	return said[done ? 1 : 0];
}

// --- the ledger: one row per step, repeated calls folded once the answer is in ------------

/** How a step ended, as the ledger marks it. */
export type StepState = 'running' | 'done' | 'empty' | 'failed' | 'not-run';

export function stepState(step: WalkStep): StepState {
	if (step.status === 'running') return 'running';
	if (step.error?.startsWith('Not run')) return 'not-run';
	if (step.error) return 'failed';
	if (step.count === 0) return 'empty';
	return 'done';
}

/** The input key that tells repeated calls of a tool apart, and what those values are called. */
const REPEATS: Record<string, { key: string; many: string; verb: string }> = {
	work_history: { key: 'system', many: 'systems', verb: 'Read recent work on' },
	experts_for_system: { key: 'system', many: 'systems', verb: 'Asked who knows best on' },
	impact_of: { key: 'system', many: 'systems', verb: 'Checked what changes together with' },
	person_profile: { key: 'login', many: 'people', verb: 'Looked up the profiles of' },
	get_entity: { key: 'uid', many: 'nodes', verb: 'Opened' },
	related_work_items: { key: 'text', many: 'searches', verb: 'Searched PRs and issues' },
	related_documents: { key: 'text', many: 'searches', verb: 'Searched docs' }
};

export interface LedgerItem {
	/** One step, or a run of the same tool folded into one row (`steps.length > 1`). */
	steps: WalkStep[];
	sentence: string;
	state: StepState;
	/** Rows returned, all steps together. */
	count: number | null;
	ms: number | null;
}

function groupSentence(steps: WalkStep[]): string {
	const tool = steps[0].tool;
	const r = REPEATS[tool];
	if (!r) return `${stepSentence(steps[0], true)}, and ${steps.length - 1} more like it`;
	const names = steps.map((s) => {
		const v = str(s.input?.[r.key]);
		return r.key === 'uid' ? shortUid(v) : r.key === 'text' ? `"${v}"` : v;
	});
	if (r.key === 'text') return `${r.verb} ${steps.length} times: ${names.join(', ')}`;
	return `${r.verb} ${steps.length} ${r.many}: ${names.join(', ')}`;
}

const sum = (xs: (number | null | undefined)[]) =>
	xs.some((x) => typeof x === 'number') ? xs.reduce<number>((a, x) => a + (x ?? 0), 0) : null;

/**
 * The graph steps of one answer as ledger rows. While the answer runs every step is its own row;
 * once it is in (`settled`), a run of two or more calls of the same tool that all returned rows
 * folds into one ("Read recent work on 4 systems: Web app, Billing, Infra, Auth"). A step that
 * found nothing or failed always keeps its own row, so it stays visible.
 */
export function ledgerItems(steps: WalkStep[], settled: boolean): LedgerItem[] {
	const graph = steps.filter((s) => s.n !== null);
	const single = (s: WalkStep): LedgerItem => ({
		steps: [s],
		sentence: stepSentence(s, s.status === 'done'),
		state: stepState(s),
		count: s.count ?? null,
		ms: s.ms ?? null
	});
	if (!settled) return graph.map(single);
	const out: LedgerItem[] = [];
	let run: WalkStep[] = [];
	const flush = () => {
		if (run.length > 1)
			out.push({ steps: run, sentence: groupSentence(run), state: 'done', count: sum(run.map((s) => s.count)), ms: sum(run.map((s) => s.ms)) });
		else if (run.length === 1) out.push(single(run[0]));
		run = [];
	};
	for (const s of graph) {
		const foldable = stepState(s) === 'done';
		if (foldable && run.length && run[0].tool === s.tool) run.push(s);
		else {
			flush();
			if (foldable) run = [s];
			else out.push(single(s));
		}
	}
	flush();
	return out;
}

/** The ledger's last row: how the newest answer check went (null before the first one). */
export interface CheckLine {
	state: 'running' | 'done' | 'failed' | 'not-run';
	text: string;
}

/**
 * The answer check row. The newest check speaks (an answer sent back is checked again); a pass
 * after send-backs says how many there were.
 */
export function checkLine(steps: WalkStep[]): CheckLine | null {
	const checks = steps.filter((s) => s.n === null);
	const check = checks.at(-1);
	if (!check) return null;
	if (check.status === 'running') return { state: 'running', text: 'Checking the answer against what was found' };
	if (check.error?.startsWith('Not run')) return { state: 'not-run', text: 'Answer check not run: the answer ended first' };
	if (check.error) return { state: 'failed', text: `Answer sent back: ${check.error}` };
	const back = checks.slice(0, -1).filter((s) => s.error && !s.error.startsWith('Not run')).length;
	if (back === 0) return { state: 'done', text: 'Checked: every citation came from a step above' };
	const times = back === 1 ? '1 send-back' : `${back} send-backs`;
	return { state: 'done', text: `Checked after ${times}: every citation came from a step above` };
}

/**
 * What a running answer is doing now, for a screen reader's live region: the newest running
 * step's sentence, "Writing the answer" while only the answer check runs, or nothing.
 */
export function progressLine(steps: WalkStep[]): string {
	const step = steps.filter((s) => s.n !== null && s.status === 'running').at(-1);
	if (step) return stepSentence(step);
	return steps.some((s) => s.n === null && s.status === 'running') ? 'Writing the answer' : '';
}

/** What one step added to the walk: its nodes and links, for lighting it while its row is hovered. */
export function stepHighlight(step: Pick<WalkStep, 'nodes' | 'rels'>): Highlight {
	return {
		nodes: new Set((step.nodes ?? []).map((n) => n.uid)),
		rels: new Set((step.rels ?? []).map(relKey))
	};
}

/** Links an earlier question found from a node this answer also touched, at most this many nodes. */
export const CARRY_MAX = 6;

/**
 * Context from earlier questions: nodes they found that are linked to a node this answer touched,
 * and those links. They are drawn dashed and faint until a step of this answer touches them, so a
 * follow-up visibly starts from what the conversation already knows.
 */
export function carryOver(earlier: WalkStep[], steps: WalkStep[], max = CARRY_MAX): { nodes: WalkNode[]; rels: WalkRel[] } {
	const now = mergeWalk(steps);
	if (now.nodes.length === 0) return { nodes: [], rels: [] };
	const here = new Set(now.nodes.map((n) => n.uid));
	const haveRel = new Set(now.rels.map((r) => r.key));
	const before = mergeWalk(earlier);
	const byUid = new Map(before.nodes.map((n) => [n.uid, n]));
	const nodes = new Map<string, WalkNode>();
	const rels: WalkRel[] = [];
	for (const r of before.rels) {
		if (haveRel.has(r.key)) continue;
		const a = here.has(r.from);
		const b = here.has(r.to);
		if (a === b) continue; // both or neither end is in this answer
		const other = a ? r.to : r.from;
		const node = byUid.get(other);
		if (!node) continue;
		if (!nodes.has(other)) {
			if (nodes.size >= max) continue;
			const { step: _step, ...plain } = node;
			nodes.set(other, plain);
		}
		const { step: _s, key: _k, ...rel } = r;
		rels.push(rel);
	}
	return { nodes: [...nodes.values()], rels };
}

/** The call as code: experts_for_system(system: "Auth"); paths read alice → carol. */
export function stepCall(step: Pick<WalkStep, 'tool' | 'input'>): string {
	const p = step.input ?? {};
	if (step.tool === 'path_between') return `path_between(${shortUid(str(p.from_uid))} → ${shortUid(str(p.to_uid))})`;
	const args = Object.entries(p).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);
	return `${step.tool}(${args.join(', ')})`;
}

export interface ChainLink {
	title: string;
	uid: string;
	/** The relationship to the next node and which way it points; absent on the last node. */
	rel?: string;
	forward?: boolean;
}
export interface RowView {
	/** A path, node by node (path_between rows). */
	chain?: ChainLink[];
	/** Otherwise one line: the row's name and a few of its numbers. */
	text?: string;
	/** The nodes the row names, to mark the citations that used it. */
	uids: string[];
}

const NAME_KEYS = ['title', 'login', 'system', 'name', 'subject', 'path', 'kind'];
const NUMBER_KEYS: [string, string][] = [
	['score', 'score'],
	['changes', 'changes'],
	['reviews', 'reviews'],
	['prs', 'PRs'],
	['prs_authored', 'PRs'],
	['co_changes', 'changed together'],
	['count', ''],
	['neighbour_count', 'links']
];

function uidsOf(value: unknown, out: string[] = []): string[] {
	if (Array.isArray(value)) value.forEach((v) => uidsOf(v, out));
	else if (value && typeof value === 'object') {
		for (const [k, v] of Object.entries(value)) {
			if ((k === 'uid' || k.endsWith('_uid')) && typeof v === 'string') out.push(v);
			else if (typeof v === 'object') uidsOf(v, out);
		}
	}
	return out;
}

/** The rows a step returned, ready to list under it. */
export function rowViews(step: Pick<WalkStep, 'tool' | 'rows'>): RowView[] {
	return (step.rows ?? []).map((raw) => {
		const row = (raw ?? {}) as Record<string, unknown>;
		if (step.tool === 'path_between') {
			const nodes = (row.nodes ?? []) as { uid: string; name?: string | null }[];
			const rels = (row.rels ?? []) as { type: string; from: string; to: string }[];
			const chain = nodes.map((n, i): ChainLink => {
				const next = nodes[i + 1];
				const rel = next && rels.find((r) => (r.from === n.uid && r.to === next.uid) || (r.from === next.uid && r.to === n.uid));
				return {
					title: n.name ?? shortUid(n.uid),
					uid: n.uid,
					...(rel ? { rel: rel.type, forward: rel.from === n.uid } : {})
				};
			});
			return { chain, uids: nodes.map((n) => n.uid) };
		}
		const nameKey = NAME_KEYS.find((k) => typeof row[k] === 'string');
		let name = nameKey ? str(row[nameKey]) : '';
		if (typeof row.number === 'number' && nameKey === 'title') name = `#${row.number} ${name}`;
		const numbers = NUMBER_KEYS.filter(([k]) => typeof row[k] === 'number')
			.slice(0, 3)
			.map(([k, label]) => {
				const v = row[k] as number;
				const n = Number.isInteger(v) ? String(v) : v.toFixed(2);
				return label ? `${label} ${n}` : n;
			});
		return { text: [name || 'row', ...numbers].join(' · '), uids: uidsOf(row) };
	});
}

// --- the answer's Markdown ---------------------------------------------------------------

export type Inline =
	| { kind: 'text' | 'bold' | 'code'; text: string }
	| { kind: 'cite'; n: number };
export type Block =
	| { kind: 'p'; inlines: Inline[] }
	| { kind: 'ul' | 'ol'; items: Inline[][] };

/** A citation marker: [1] or [1, 2]; group 1 holds the numbers. */
const CITE = String.raw`\[(\d+(?:\s*,\s*\d+)*)\]`;
const INLINE = new RegExp(`${/\*\*(.+?)\*\*|`([^`]+)`/.source}|${CITE}`, 'g');

export function inlines(text: string): Inline[] {
	const out: Inline[] = [];
	let at = 0;
	for (const m of text.matchAll(INLINE)) {
		if (m.index > at) out.push({ kind: 'text', text: text.slice(at, m.index) });
		if (m[1] !== undefined) out.push({ kind: 'bold', text: m[1] });
		else if (m[2] !== undefined) out.push({ kind: 'code', text: m[2] });
		else for (const n of m[3].split(',')) out.push({ kind: 'cite', n: Number(n.trim()) });
		at = m.index + m[0].length;
	}
	if (at < text.length) out.push({ kind: 'text', text: text.slice(at) });
	return out;
}

/**
 * The few Markdown forms answers use: paragraphs, - and 1. lists, **bold**, `code` and [n]
 * citations. Everything is text; nothing becomes HTML, so an answer can never inject markup.
 */
export function answerBlocks(text: string): Block[] {
	const blocks: Block[] = [];
	let para: string[] = [];
	const flush = () => {
		if (para.length) blocks.push({ kind: 'p', inlines: inlines(para.join(' ')) });
		para = [];
	};
	for (const raw of text.split('\n')) {
		const line = raw.trim();
		const item = /^([-*]|\d+[.)])\s+(.*)$/.exec(line);
		if (!line) {
			flush();
		} else if (item) {
			flush();
			const kind = /^\d/.test(item[1]) ? 'ol' : 'ul';
			const last = blocks.at(-1);
			if (last && last.kind === kind) last.items.push(inlines(item[2]));
			else blocks.push({ kind, items: [inlines(item[2])] });
		} else {
			para.push(line.replace(/^#+\s*/, ''));
		}
	}
	flush();
	return blocks;
}

/** The answer's text without its citation markers (and the space before each), for copying. */
export function answerPlainText(text: string): string {
	return text.replace(new RegExp(String.raw`\s*${CITE}`, 'g'), '');
}
