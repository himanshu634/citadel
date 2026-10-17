/**
 * The Systems page's reading of agent runs (design direction A, "the map with the agent's
 * trail"): which run to show, where each step sits on the company map, and the words for it.
 *
 * A step sits on the node it was about (`subjectOf`: the system it read, the node it opened),
 * else on the first node it returned that the map draws. Steps that touch nothing drawn (the
 * answer check, an MCP call, a folded comment) keep their place in the list, with no point.
 * Consecutive steps on the same node share one point, so their numbers never overlap.
 */
import type { ActivityRun, ActivityStep } from './types';
import { stepSentence, subjectOf } from './walk';

export interface TrailPoint {
	uid: string;
	/** The step numbers that sit on this node, in order. */
	ns: number[];
}

export interface Trail {
	points: TrailPoint[];
	/** Every drawn node the run touched. */
	lit: Set<string>;
	/** Where the agent is now: the node of its latest step while the run is going, else null. */
	current: string | null;
}

/** The agents by the name the page gives them. */
const ACTORS: Record<string, string> = { brain: 'Ask agent', keeper: 'Keeper', pm: 'pm', qa: 'qa' };

export function actorName(actor: string): string {
	return ACTORS[actor] ?? actor;
}

/** The run the page opens on: one that is still going, else the newest. */
export function featured(runs: ActivityRun[]): ActivityRun | null {
	return runs.find((r) => r.status === 'running') ?? runs[0] ?? null;
}

/** The node a step sits on, or null when it touched nothing the map draws. */
export function anchorOf(step: ActivityStep, drawn: (uid: string) => boolean): string | null {
	if (step.kind !== 'graph') return null;
	const about = subjectOf(step);
	if (about && drawn(about)) return about;
	return step.touched.find(drawn) ?? null;
}

export function trailOf(run: ActivityRun, drawn: (uid: string) => boolean): Trail {
	const points: TrailPoint[] = [];
	const lit = new Set<string>();
	for (const step of run.steps) {
		for (const uid of step.touched) if (drawn(uid)) lit.add(uid);
		const uid = anchorOf(step, drawn);
		if (!uid) continue;
		const last = points.at(-1);
		if (last?.uid === uid) last.ns.push(step.n);
		else points.push({ uid, ns: [step.n] });
	}
	const current = run.status === 'running' ? (points.at(-1)?.uid ?? null) : null;
	return { points, lit, current };
}

/** What a step did, in the Ask page's words; present tense while it runs. */
export function stepLine(step: ActivityStep): string {
	if (step.kind === 'mcp' || step.kind === 'server') {
		return step.status === 'running' ? `Calling ${step.tool}` : `Called ${step.tool}`;
	}
	return stepSentence(step, step.status !== 'running');
}

/** What the agent is doing now, for the marker on the map: its running step, else thinking. */
export function doingNow(run: ActivityRun): string {
	const step = run.steps.findLast((s) => s.status === 'running');
	return step ? stepLine(step) : 'Thinking about the next step';
}

/** "4 steps · 2 not on the map", the line under a run's title. */
export function stepsSummary(run: ActivityRun, trail: Trail): string {
	const total = run.steps.length;
	const placed = trail.points.reduce((sum, p) => sum + p.ns.length, 0);
	const words = [`${total} ${total === 1 ? 'step' : 'steps'}`];
	if (total && placed < total) words.push(`${total - placed} not on the map`);
	return words.join(' · ');
}
