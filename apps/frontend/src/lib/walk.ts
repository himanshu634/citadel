/**
 * The agent's walk through the graph, as the Ask page draws it (design direction D).
 *
 * Why: each tool call arrives with the nodes and relationships it touched (agents/walk.py).
 * This module merges the steps of one answer into one picture, lays it out so earlier nodes stay
 * put as new steps arrive, works out what a citation lights up, and turns rows, calls and the
 * answer's Markdown into plain values the components render. Pure: no Svelte, no fetch.
 */
import { codeRef, codeUrl, labelRuns, refContext, refUrl, textRuns, type RefContext, type TextRun } from './links';
import { NODE_LABELS, type AskSource, type NodeType, type WalkNode, type WalkRel, type WalkStep } from './types';

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

/**
 * What kind of source an answer cites: a graph node's label, or "MCP result" for what a tool on
 * an outside MCP server returned (uid `mcp:<server>/<tool>`, label `MCP`; not in the walk).
 */
export function sourceKind(label: string | null | undefined): string {
	if (label === 'MCP') return 'MCP result';
	if (label === 'Claim') return 'Keeper claim';
	return NODE_LABELS[nodeType(label)];
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
const MARGIN_Y = 26;

function hash(s: string): number {
	let h = 2166136261;
	for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
	return (h >>> 0) / 4294967296;
}

const NODE_HALF_HEIGHT = 15;
const GAP = 6;

/**
 * Push apart nodes whose boxes overlap, along the axis that needs the smaller move. Fans place
 * centres; pills are wide, so this pass is what keeps two names from printing on each other.
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

// --- following the agent (design direction P, round 5) -------------------------------------

/**
 * How one step plays, in ms. The mark glides to where the query starts (CALL, held while the tool
 * still runs), links grow out of it (GROW, however many there are), then the step settles. A step
 * that found nothing ripples for EMPTY instead of growing. Keep `WALK_STEP_MS` the sum: a replay
 * reveals one ledger row per played step.
 */
export const WALK_MS = { call: 450, grow: 1400, settle: 350, empty: 800 } as const;
export const WALK_STEP_MS = WALK_MS.call + WALK_MS.grow + WALK_MS.settle;

/** Where a query starts: the node it was asked about (a system, a person, an opened uid), if any. */
export function stepAnchor(step: Pick<WalkStep, 'tool' | 'input'>): string | null {
	const about = subjectOf(step);
	if (about) return about;
	const p = step.input ?? {};
	if (typeof p.login === 'string') return `person:${p.login.toLowerCase()}`;
	if (typeof p.system === 'string') return `system:${p.system}`;
	if (typeof p.uid === 'string') return p.uid;
	if (typeof p.from_uid === 'string') return p.from_uid; // path_between walks from one end
	return null;
}

/**
 * Where steps start when their anchor is not drawn yet (or they have none): the middle first,
 * then round it, so each query gets a place of its own and its finds fan out around it.
 */
const SPOTS: Point[] = [
	{ x: 320, y: 210 },
	{ x: 180, y: 140 },
	{ x: 460, y: 280 },
	{ x: 460, y: 140 },
	{ x: 180, y: 280 },
	{ x: 320, y: 100 },
	{ x: 320, y: 320 },
	{ x: 120, y: 210 },
	{ x: 520, y: 210 }
];
/** A list with no links (list_systems) bigger than this goes round the edge, not into a fan. */
const LIST_RING_MIN = 7;

export interface FollowLayout {
	pos: Map<string, Point>;
	/** Where each graph step started (by step number): its anchor, or the spot it was given. */
	spots: Map<number, Point>;
}

/** Hops from `start` over `rels`, both directions. */
function hopsFrom(start: string | null, rels: readonly WalkRel[]): Map<string, number> {
	const hop = new Map<string, number>();
	if (!start) return hop;
	const next = new Map<string, string[]>();
	for (const r of rels) {
		next.set(r.from, [...(next.get(r.from) ?? []), r.to]);
		next.set(r.to, [...(next.get(r.to) ?? []), r.from]);
	}
	hop.set(start, 0);
	let ring = [start];
	while (ring.length) {
		const out: string[] = [];
		for (const u of ring)
			for (const v of next.get(u) ?? [])
				if (!hop.has(v)) {
					hop.set(v, hop.get(u)! + 1);
					out.push(v);
				}
		ring = out;
	}
	return hop;
}

/**
 * Positions that read as the agent's walk: each step's new nodes fan out around where the step
 * started, nearer for one hop, further for two. A step about a node an earlier step grew from
 * grows from it in place; otherwise the anchor glides (or the step goes) to the next free spot,
 * so a system found inside one fan does not grow its own fan on top of it. A long
 * list with no links (the systems) sits round the edge. Deterministic and incremental: the layout
 * of the first k steps is the first k steps of a longer walk, so a node never jumps when a step
 * arrives. `carried` (context from earlier questions) sits beside the node it links to.
 */
export function layoutFollow(
	steps: readonly WalkStep[],
	halfWidth: (uid: string) => number = () => 8,
	carried: { nodes: readonly WalkNode[]; rels: readonly WalkRel[] } = { nodes: [], rels: [] }
): FollowLayout {
	const pos = new Map<string, Point>();
	const spots = new Map<number, Point>();
	/** Nodes a step already grew from: a later step about them grows in place. */
	const started = new Set<string>();
	let spot = 0;
	let listed = 0;
	let last: Point = SPOTS[0];
	const clamp = (p: Point): Point => ({
		x: Math.min(STAGE.width - 30, Math.max(30, p.x)),
		y: Math.min(STAGE.height - MARGIN_Y, Math.max(MARGIN_Y, p.y))
	});
	for (const s of steps) {
		if (s.n === null) continue;
		const nodes = s.nodes ?? [];
		const rels = s.rels ?? [];
		const ids = new Set(nodes.map((n) => n.uid));
		const fresh = nodes.map((n) => n.uid).filter((u) => !pos.has(u));
		const wanted = stepAnchor(s);
		const anchor = wanted && (ids.has(wanted) || pos.has(wanted)) ? wanted : null;
		if (nodes.length === 0) {
			spots.set(s.n, anchor && pos.has(anchor) ? pos.get(anchor)! : last);
			continue;
		}
		const old = new Set(pos.keys());
		if (!anchor && rels.length === 0 && fresh.length >= LIST_RING_MIN) {
			// A list: round the edge, in golden-angle steps so a second list fills the gaps.
			for (const u of fresh) {
				const a = -Math.PI / 2 + listed++ * 2.399963;
				pos.set(u, { x: 320 + Math.cos(a) * 290, y: 210 + Math.sin(a) * 182 });
			}
			spots.set(s.n, SPOTS[0]);
			last = SPOTS[0];
		} else {
			let c: Point;
			if (anchor && pos.has(anchor) && started.has(anchor)) c = pos.get(anchor)!;
			else {
				c = SPOTS[spot++ % SPOTS.length];
				if (anchor) pos.set(anchor, c);
			}
			spots.set(s.n, c);
			last = c;
			if (anchor) started.add(anchor);
			const hop = hopsFrom(anchor, rels);
			const rings = new Map<number, string[]>();
			for (const u of fresh) {
				if (u === anchor) continue;
				const h = hop.get(u) ?? 1;
				rings.set(h, [...(rings.get(h) ?? []), u]);
			}
			for (const [h, list] of rings) {
				const turn = hash(`${s.n}:${h}`) * Math.PI * 2;
				list.forEach((u, j) => {
					const a = turn + (j / list.length) * Math.PI * 2;
					const r = 46 + (h - 1) * 48 + (j % 3) * 12;
					pos.set(u, clamp({ x: c.x + Math.cos(a) * r * 1.25, y: c.y + Math.sin(a) * r * 0.8 }));
				});
			}
		}
		separate(pos, anchor, old, halfWidth); // the place the step grew from stays put
	}
	const extra = carried.nodes.filter((n) => !pos.has(n.uid));
	if (extra.length) {
		const old = new Set(pos.keys());
		for (const n of extra) {
			const r = carried.rels.find((x) => (x.from === n.uid && pos.has(x.to)) || (x.to === n.uid && pos.has(x.from)));
			const base = (r && pos.get(r.from === n.uid ? r.to : r.from)) || SPOTS[0];
			const a = hash(n.uid) * Math.PI * 2;
			pos.set(n.uid, clamp({ x: base.x + Math.cos(a) * 70, y: base.y + Math.sin(a) * 48 }));
		}
		separate(pos, null, old, halfWidth);
	}
	return { pos, spots };
}

export interface Growth {
	/** Each link of the step: it grows from `src` (the end nearer the anchor) to `dst`. */
	links: { key: string; src: string; dst: string; t0: number; t1: number }[];
	/** When each node the step brings first appears: its first link reaches it. */
	arrive: Map<string, number>;
	/** Nodes no link reaches (a list, a search): a spoke from the mark brings them. */
	spokes: { uid: string; t0: number; t1: number }[];
}

/**
 * When each part of one step grows, in ms from the start of its grow phase, inside
 * `WALK_MS.grow` however many links it has: hop 1 first, then hop 2, staggered within a hop.
 * `drawn` holds the nodes earlier steps already show (they need no arrival).
 */
export function growSchedule(step: WalkStep, drawn: ReadonlySet<string>): Growth {
	const nodes = (step.nodes ?? []).map((n) => n.uid);
	const rels = step.rels ?? [];
	const wanted = stepAnchor(step);
	const anchor = wanted && (nodes.includes(wanted) || drawn.has(wanted)) ? wanted : null;
	const hop = hopsFrom(anchor, rels);
	const span = WALK_MS.grow * 0.8;
	const deepest = Math.max(1, ...rels.map((r) => Math.max(hop.get(r.from) ?? 1, hop.get(r.to) ?? 1)));
	const per = span / deepest;
	const byHop = new Map<number, WalkRel[]>();
	for (const r of rels) {
		const h = Math.max(1, hop.get(r.from) ?? 1, hop.get(r.to) ?? 1);
		byHop.set(h, [...(byHop.get(h) ?? []), r]);
	}
	const links: Growth['links'] = [];
	for (const [h, list] of byHop)
		list.forEach((r, j) => {
			const a = hop.get(r.from) ?? 99;
			const b = hop.get(r.to) ?? 99;
			const t0 = (h - 1) * per + (j / list.length) * per * 0.55;
			links.push({ key: relKey(r), src: a <= b ? r.from : r.to, dst: a <= b ? r.to : r.from, t0, t1: t0 + Math.max(260, per * 0.45) });
		});
	const arrive = new Map<string, number>();
	if (anchor && !drawn.has(anchor)) arrive.set(anchor, 0);
	for (const l of links) {
		for (const [u, t] of [
			[l.src, l.t0],
			[l.dst, l.t1]
		] as const)
			if (!drawn.has(u) && (!arrive.has(u) || arrive.get(u)! > t)) arrive.set(u, t);
	}
	const lonely = nodes.filter((u) => !drawn.has(u) && !arrive.has(u));
	const spokes = lonely.map((uid, j) => {
		const t0 = (j / lonely.length) * span * 0.7;
		arrive.set(uid, t0 + 320);
		return { uid, t0, t1: t0 + 320 };
	});
	return { links, arrive, spokes };
}

/** "authored 30 · reviewed 22": the relationships a step read, busiest first. */
export function relTypesLine(rels: readonly WalkRel[]): string {
	const count = new Map<string, number>();
	for (const r of rels) {
		const t = (r.note ?? r.type).toLowerCase();
		count.set(t, (count.get(t) ?? 0) + 1);
	}
	return [...count]
		.sort((a, b) => b[1] - a[1])
		.slice(0, 4)
		.map(([t, n]) => `${t} ${n}`)
		.join(' · ');
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
	semantic_search: (p) => [`Searching by meaning for "${str(p.text)}"`, `Searched by meaning for "${str(p.text)}"`],
	get_entity: (p) => [`Opening ${shortUid(str(p.uid))}`, `Opened ${shortUid(str(p.uid))}`],
	list_systems: () => ['Listing the systems', 'Listed the systems'],
	owners_vs_experts: () => ['Comparing declared owners with who does the work', 'Compared declared owners with who does the work'],
	recent_work_items: () => ['Reading the latest work', 'Read the latest work'],
	people_activity: () => ['Listing people and their activity', 'Listed people and their activity'],
	collaborators: (p) =>
		p.login
			? [`Finding who works most with ${str(p.login)}`, `Found who works most with ${str(p.login)}`]
			: ['Finding who works most closely together', 'Found who works most closely together'],
	issues_by_system: () => ['Counting issues per system', 'Counted issues per system'],
	central_nodes: (p) => {
		const what = { WorkItem: 'work items', Document: 'documents' }[str(p.label)] ?? 'systems';
		return [`Ranking the most central ${what}`, `Ranked the most central ${what}`];
	},
	bottlenecks: () => ['Finding the work everything else goes through', 'Found the work everything else goes through'],
	graph_stats: () => ['Counting what the graph holds', 'Counted what the graph holds'],
	submit_answer: () => ['Checking the answer against what was found', 'Checked the answer against what was found'],
	// Ask interviewing the person about the brain's gaps.
	open_gaps: () => ['Reading what the brain could not answer', 'Read what the brain could not answer'],
	record_testimony: (p) => [
		`Filing what you said about ${shortUid(str(p.subject_uid))}`,
		`Filed what you said about ${shortUid(str(p.subject_uid))} for a lead to approve`
	],
	// The Keeper review's tools and the submits of its pm, qa and keeper jobs.
	keeper_notes: (p) => [`Reading the Keeper's notes on ${shortUid(str(p.uid))}`, `Read the Keeper's notes on ${shortUid(str(p.uid))}`],
	submit_consult: (p) => [
		'Answering the Keeper',
		p.can_ground === false
			? 'Told the Keeper the graph does not support a claim'
			: `Drafted ${p.kind ? `${article(str(p.kind))} ${str(p.kind)} claim` : 'a claim'} for the Keeper`
	],
	submit_keeper_decision: (p) => [
		'Deciding the gap',
		p.outcome === 'needs_person'
			? 'Decided the gap needs a person'
			: p.outcome === 'dismiss'
				? 'Dismissed the gap'
				: 'Decided to write a claim'
	],
	submit_follow_up: (p) => [
		'Opening a follow-up',
		p.title ? `Opened a follow-up: ${str(p.title)}` : 'Opened a follow-up'
	]
};

/** "a" or "an" before a word. */
const article = (word: string) => (/^[aeiou]/i.test(word) ? 'an' : 'a');

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
	related_documents: { key: 'text', many: 'searches', verb: 'Searched docs' },
	semantic_search: { key: 'text', many: 'searches', verb: 'Searched by meaning' }
};

/** The input keys that name a node in a step's sentence ("Opened PR #10", "how alice and PR #3 connect"). */
const NAMED_KEYS = ['uid', 'from_uid', 'to_uid'];

/** The uids a step's input names, in the order its sentence says them. */
export function namedUids(input: Record<string, unknown> | null | undefined): string[] {
	return NAMED_KEYS.map((k) => input?.[k]).filter((v): v is string => typeof v === 'string');
}

/**
 * A sentence with the nodes it names linked (each once): to `urlOf(uid)`, else to the github.com
 * page of a GitHub uid. Labels are `shortUid`'s, as the sentence wrote them.
 */
export function sentenceRuns(sentence: string, uids: string[], urlOf: (uid: string) => string | null = () => null): TextRun[] {
	return labelRuns(
		sentence,
		[...new Set(uids)].map((uid) => ({ label: shortUid(uid), href: refUrl(uid, urlOf(uid)) }))
	);
}

/** Node urls by uid from what steps returned: their walk nodes and every uid'd row (any depth). */
export function stepUrls(steps: Pick<WalkStep, 'nodes' | 'rows'>[]): Map<string, string> {
	const out = new Map<string, string>();
	const visit = (v: unknown) => {
		if (Array.isArray(v)) return v.forEach(visit);
		if (!v || typeof v !== 'object') return;
		const o = v as { uid?: unknown; url?: unknown };
		if (typeof o.uid === 'string' && typeof o.url === 'string' && !out.has(o.uid)) out.set(o.uid, o.url);
		for (const x of Object.values(o)) if (x && typeof x === 'object') visit(x);
	};
	for (const step of steps) visit([step.nodes ?? [], step.rows ?? []]);
	return out;
}

/** A ledger row's sentence with the nodes it names linked to their pages. */
export function ledgerRuns(item: LedgerItem): TextRun[] {
	const urls = stepUrls(item.steps);
	return sentenceRuns(item.sentence, item.steps.flatMap((s) => namedUids(s.input)), (uid) => urls.get(uid) ?? null);
}

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
	/** Where the node opens, when it has a page. */
	url?: string;
	/** The relationship to the next node and which way it points; absent on the last node. */
	rel?: string;
	forward?: boolean;
}
export interface RowView {
	/** A path, node by node (path_between rows). */
	chain?: ChainLink[];
	/** Otherwise one line: the row's name and a few of its numbers. */
	text?: string;
	/** Where the row's node opens (its own url, else one made from a GitHub uid). */
	url?: string;
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
			const nodes = (row.nodes ?? []) as { uid: string; name?: string | null; url?: string | null }[];
			const rels = (row.rels ?? []) as { type: string; from: string; to: string }[];
			const chain = nodes.map((n, i): ChainLink => {
				const next = nodes[i + 1];
				const rel = next && rels.find((r) => (r.from === n.uid && r.to === next.uid) || (r.from === next.uid && r.to === n.uid));
				const url = refUrl(n.uid, n.url);
				return {
					title: n.name ?? shortUid(n.uid),
					uid: n.uid,
					...(url ? { url } : {}),
					...(rel ? { rel: rel.type, forward: rel.from === n.uid } : {})
				};
			});
			return { chain, uids: nodes.map((n) => n.uid) };
		}
		const nameKey = NAME_KEYS.find((k) => typeof row[k] === 'string');
		let name = nameKey ? str(row[nameKey]) : '';
		if (typeof row.number === 'number' && (nameKey === 'title' || nameKey === 'name')) name = `#${row.number} ${name}`;
		const numbers = NUMBER_KEYS.filter(([k]) => typeof row[k] === 'number')
			.slice(0, 3)
			.map(([k, label]) => {
				const v = row[k] as number;
				// PageRank scores are small: 0.0068 keeps two digits instead of reading 0.01
				const n = Number.isInteger(v) ? String(v) : Math.abs(v) < 0.01 ? v.toPrecision(2) : v.toFixed(2);
				return label ? `${label} ${n}` : n;
			});
		const url = refUrl(typeof row.uid === 'string' ? row.uid : null, typeof row.url === 'string' ? row.url : null);
		return { text: [name || 'row', ...numbers].join(' · '), ...(url ? { url } : {}), uids: uidsOf(row) };
	});
}

// --- the answer's Markdown ---------------------------------------------------------------

export type Inline =
	| { kind: 'text' | 'bold' | 'code'; text: string }
	| { kind: 'cite'; n: number }
	/** A reference that opens where it lives: `#12`, `owner/name#12` or a file path (`code`). */
	| { kind: 'link'; text: string; href: string; code: boolean };
export type Block =
	| { kind: 'p'; inlines: Inline[] }
	| { kind: 'ul' | 'ol'; items: Inline[][] };

/** A citation marker: [1] or [1, 2]; group 1 holds the numbers. */
const CITE = String.raw`\[(\d+(?:\s*,\s*\d+)*)\]`;
const INLINE = new RegExp(`${/\*\*(.+?)\*\*|`([^`]+)`/.source}|${CITE}`, 'g');

/**
 * One line's inlines. With `refs`, `#12`, `owner/name#12` and paths in the text, and `code` runs
 * that are a file path, become links where they resolve (`textRuns`, `codeRef` in links.ts).
 */
export function inlines(text: string, refs?: RefContext): Inline[] {
	const out: Inline[] = [];
	const plain = (t: string) => {
		if (!refs) return void out.push({ kind: 'text', text: t });
		for (const run of textRuns(t, refs))
			out.push(run.href ? { kind: 'link', text: run.text, href: run.href, code: false } : { kind: 'text', text: run.text });
	};
	let at = 0;
	for (const m of text.matchAll(INLINE)) {
		if (m.index > at) plain(text.slice(at, m.index));
		if (m[1] !== undefined) out.push({ kind: 'bold', text: m[1] });
		else if (m[2] !== undefined) {
			const ref = refs && codeRef(m[2]);
			const href = ref && refs ? codeUrl(ref, refs) : null;
			out.push(href ? { kind: 'link', text: m[2], href, code: true } : { kind: 'code', text: m[2] });
		} else for (const n of m[3].split(',')) out.push({ kind: 'cite', n: Number(n.trim()) });
		at = m.index + m[0].length;
	}
	if (at < text.length) plain(text.slice(at));
	return out;
}

/**
 * The few Markdown forms answers use: paragraphs, - and 1. lists, **bold**, `code` and [n]
 * citations, and with `refs` the links of `inlines`. Everything is text; nothing becomes HTML, so
 * an answer can never inject markup (a link's href comes only from links.ts, http(s) only).
 */
export function answerBlocks(text: string, refs?: RefContext): Block[] {
	const blocks: Block[] = [];
	let para: string[] = [];
	const flush = () => {
		if (para.length) blocks.push({ kind: 'p', inlines: inlines(para.join(' '), refs) });
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
			if (last && last.kind === kind) last.items.push(inlines(item[2], refs));
			else blocks.push({ kind, items: [inlines(item[2], refs)] });
		} else {
			// A heading's hashes need a space after them: `#12 fixed it` keeps its number.
			para.push(line.replace(/^#{1,6}\s+/, ''));
		}
	}
	flush();
	return blocks;
}

/**
 * What an answer's `#12` and paths resolve against: the nodes and rows of its steps (and of
 * earlier questions in the thread), its sources, and the company's GitHub repos.
 */
export function answerRefs(steps: WalkStep[], sources: AskSource[] = [], repos: string[] = []): RefContext {
	return refContext([sources, steps.map((s) => [s.nodes ?? [], s.rows ?? []])], repos);
}

/** The answer's text without its citation markers (and the space before each), for copying. */
export function answerPlainText(text: string): string {
	return text.replace(new RegExp(String.raw`\s*${CITE}`, 'g'), '');
}
