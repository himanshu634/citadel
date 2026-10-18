// Agent runs for the gallery: Ask turns on the synthetic company (uids from graph-samples.ts).
import type { ActivityRun, ActivityStep } from '$lib/types';

function step(n: number, tool: string, input: Record<string, unknown>, touched: string[], extra: Partial<ActivityStep> = {}): ActivityStep {
	return { n, actor: 'brain', tool, kind: 'graph', input, status: 'done', count: touched.length, error: null, touched, ...extra };
}

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

/** Going now: four steps done across Billing and Auth, the fifth running on Auth. */
export const runningRun: ActivityRun = {
	id: 'ask:sample:1',
	source: 'ask',
	actor: 'brain',
	title: 'Who decides the refund rules?',
	status: 'running',
	started_at: at(1),
	ended_at: null,
	thread_id: 'sample',
	steps: [
		step(1, 'work_history', { system: 'Billing' }, ['system:Billing', 'synthetic:pr:4', 'synthetic:pr:5']),
		step(2, 'experts_for_system', { system: 'Billing' }, ['person:bob', 'team:payments']),
		step(3, 'get_entity', { uid: 'synthetic:issue:12' }, ['synthetic:issue:12']),
		step(4, 'related_documents', { text: 'refund policy' }, ['chunk:refunds'], { count: 0 }),
		step(5, 'impact_of', { system: 'Auth' }, [], { status: 'running', count: null })
	]
};

/** Done: the trail stays, with no ring; the answer check has no point on the map. */
export const doneRun: ActivityRun = {
	...runningRun,
	id: 'ask:sample:2',
	title: 'Which systems usually change together?',
	status: 'done',
	started_at: at(42),
	ended_at: at(41),
	steps: [
		step(1, 'impact_of', { system: 'Web app' }, ['system:Web app', 'system:Billing']),
		step(2, 'impact_of', { system: 'Infra' }, ['system:Infra', 'system:Auth']),
		step(3, 'submit_answer', {}, [], { kind: 'submit', count: null })
	]
};

/** Failed before its first step. */
export const failedRun: ActivityRun = {
	...runningRun,
	id: 'ask:sample:3',
	title: 'Who works most closely with whom?',
	status: 'failed',
	started_at: at(180),
	ended_at: at(180),
	steps: []
};

/** The Archivist's own run (Systems page): the same step list, its actor named. */
export const archivistRun: ActivityRun = {
	id: 'archivist:sample:1',
	source: 'archive',
	actor: 'archivist',
	title: 'the 2021 move to JWT sessions',
	status: 'done',
	started_at: at(6),
	ended_at: at(5),
	thread_id: null,
	steps: [
		step(1, 'archive_search', { source: 'github', terms: 'jwt sessions' }, [], { actor: 'archivist', kind: 'server', count: 3 }),
		step(2, 'archive_fetch', { source: 'github', id: 'synthetic:pr:1' }, [], { actor: 'archivist', kind: 'server' }),
		step(3, 'submit_archive_answer', { outcome: 'found' }, [], { actor: 'archivist', kind: 'submit', count: null })
	]
};
