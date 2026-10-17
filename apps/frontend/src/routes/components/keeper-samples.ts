// The Keeper for the gallery: claims, log lines and a review on the synthetic company.
import type { ActivityRun, ActivityStep, AskAnswer, Claim, LogEntry } from '$lib/types';
import type { EvidenceRef } from '$lib/keeper';
import { answer } from './walk-samples';

const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

/** Waiting for a lead: Billing is high impact. */
export const pendingClaim: Claim = {
	uid: 'claim:3fa2c1d0e9b8',
	kind: 'expert',
	subject: 'system:Billing',
	statement: 'bob decides the refund rules in Billing.',
	value: 'person:bob',
	about: ['system:Billing'],
	evidence: ['synthetic:pr:4', 'synthetic:issue:12', 'person:bob'],
	status: 'pending_approval',
	critical: true,
	critical_reasons: ['high_impact_system'],
	conflict: null,
	valid_from: null,
	valid_to: null,
	author: 'keeper',
	approved_by: null,
	why: null,
	gap: 'gap:refunds',
	created_at: at(8),
	updated_at: at(8),
	follow_up_tries: 0
};

export const pendingEvidence: EvidenceRef[] = [
	{ uid: 'synthetic:pr:4', label: 'WorkItem', title: 'feat(billing): partial refunds', url: 'https://example.com/synthetic/app/pull/4' },
	{ uid: 'synthetic:issue:12', label: 'WorkItem', title: 'Refunds over 30 days need sign-off', url: null },
	{ uid: 'person:bob', label: 'Person', title: 'bob', url: null }
];

/** Every reason at once, no evidence, long text. */
export const longClaim: Claim = {
	...pendingClaim,
	uid: 'claim:long',
	kind: 'decision',
	statement:
		'The payments team decided in July to move invoice emails out of the checkout request and into a queue, so a slow mail provider never holds up a payment again.',
	evidence: [],
	critical_reasons: ['replaces_claim', 'high_impact_system', 'no_source_evidence']
};

const entry = (minutesAgo: number, actor: string, action: string, extra: Partial<LogEntry> = {}): LogEntry => ({
	uid: `log:${minutesAgo}-${action}`,
	at: at(minutesAgo),
	actor,
	action,
	why: null,
	gap: null,
	claim: null,
	evidence: [],
	...extra
});

export const gapTexts = new Map([
	['gap:refunds', 'Who decides the refund rules?'],
	['gap:closest', 'Who works most closely with whom?']
]);

export const logEntries: LogEntry[] = [
	entry(1, 'pm', 'follow_up_opened', { claim: 'claim:infra', why: 'Update CODEOWNERS for Auth' }),
	entry(2, 'keeper', 'claim_conflicts_with_source', { claim: 'claim:auth', why: 'declared owners: identity' }),
	entry(3, 'auto', 'claim_written', { claim: 'claim:infra' }),
	entry(4, 'keeper', 'claim_queued', { gap: 'gap:refunds', claim: pendingClaim.uid, why: 'high_impact_system' }),
	entry(5, 'keeper', 'needs_person', { gap: 'gap:closest', why: 'pm and qa could not ground it.' }),
	entry(6, 'keeper', 'consulted', { gap: 'gap:refunds', why: 'asked pm' }),
	entry(7, 'keeper', 'review_start', { why: 'review:ab12cd34: manual, budget 3' }),
	entry(60 * 30, 'Dana Lee', 'claim_rejected', { claim: 'claim:old', why: 'Bob left the payments team in August.' })
];

function step(n: number, actor: string, tool: string, input: Record<string, unknown>, touched: string[], extra: Partial<ActivityStep> = {}): ActivityStep {
	return { n, actor, tool, kind: 'graph', input, status: 'done', count: touched.length, error: null, touched, ...extra };
}

/** A review going now: pm and qa answered the consult, the Keeper is reading Billing. */
export const keeperRun: ActivityRun = {
	id: 'keeper:review:ab12cd34',
	source: 'keeper',
	actor: 'keeper',
	title: 'Who decides the refund rules?',
	status: 'running',
	started_at: at(2),
	ended_at: null,
	thread_id: null,
	steps: [
		step(1, 'pm', 'work_history', { system: 'Billing' }, ['system:Billing', 'synthetic:pr:4', 'synthetic:pr:5']),
		step(2, 'pm', 'submit_consult', { subject: 'consult:gap:refunds:pm:0', can_ground: true, kind: 'expert' }, [], { kind: 'submit', count: null }),
		step(3, 'qa', 'get_entity', { uid: 'synthetic:issue:12' }, ['synthetic:issue:12']),
		step(4, 'qa', 'submit_consult', { subject: 'consult:gap:refunds:qa:0', can_ground: false }, [], { kind: 'submit', count: null }),
		step(5, 'keeper', 'experts_for_system', { system: 'Billing' }, [], { status: 'running', count: null })
	]
};

/** An Ask answer that cites a Keeper claim next to a source fact. */
export const withClaim: AskAnswer = {
	...answer,
	text: 'Bob decides the refund rules [1]; he wrote the partial refunds change [2].',
	sources: [
		{ uid: 'claim:3fa2c1d0e9b8', title: 'bob decides the refund rules in Billing.', url: null, label: 'Claim', step: 1 },
		answer.sources[0]
	]
};
