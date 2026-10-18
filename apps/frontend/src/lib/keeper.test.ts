import { describe, expect, it } from 'vitest';
import { ApiError } from './api/client';
import {
	checkApproval,
	criticalLine,
	decidedLine,
	decidedTag,
	decisionError,
	keeperRunning,
	evidenceRefs,
	keeperRunsKey,
	logTime,
	railLog,
	logSentence,
	logWhy,
	reasonRows,
	reasonWords,
	reviewNote,
	whoName
} from './keeper';
import type { ActivityRun, LogEntry, Review } from './types';

function entry(action: string, extra: Partial<LogEntry> = {}): LogEntry {
	return { uid: 'log:1', at: '2026-10-17T10:00:00Z', actor: 'keeper', action, why: null, gap: null, claim: null, evidence: [], ...extra };
}

function review(extra: Partial<Review> = {}): Review {
	return {
		uid: 'review:ab12cd34',
		slug: 'synthetic',
		trigger: 'manual',
		state: 'running',
		budget: 3,
		started_at: '2026-10-17T10:00:00Z',
		ended_at: null,
		stop: null,
		gaps: [],
		gap_text: null,
		...extra
	};
}

function run(id: string, source: ActivityRun['source'], status: ActivityRun['status']): ActivityRun {
	return { id, source, actor: source === 'ask' ? 'brain' : 'keeper', title: 't', status, started_at: '2026-10-17T10:00:00Z', ended_at: null, thread_id: null, steps: [] };
}

describe('critical reasons', () => {
	it('says each reason in words', () => {
		expect(reasonWords('replaces_claim')).toBe('it replaces an earlier Keeper update');
		expect(reasonWords('high_impact_system')).toBe('it touches a high-impact system');
		expect(reasonWords('no_source_evidence')).toBe('no commit, PR, ticket or doc is behind it');
		expect(reasonWords('from_person')).toBe('a person told it in Ask');
		expect(reasonWords('something_new')).toBe('something new');
	});
	it('joins them into one line', () => {
		expect(criticalLine(['high_impact_system'])).toBe('Needs a lead because it touches a high-impact system.');
		expect(criticalLine(['replaces_claim', 'high_impact_system', 'no_source_evidence'])).toBe(
			'Needs a lead because it replaces an earlier Keeper update, it touches a high-impact system and no commit, PR, ticket or doc is behind it.'
		);
		expect(criticalLine([])).toBe('Needs a lead.');
	});
});

describe('who', () => {
	it('names the Keeper for auto and keeper, keeps every other name', () => {
		expect(whoName('auto')).toBe('Keeper');
		expect(whoName('keeper')).toBe('Keeper');
		expect(whoName('pm')).toBe('pm');
		expect(whoName('Dana Lee')).toBe('Dana Lee');
		expect(whoName('agent:pm')).toBe('pm');
		expect(whoName('agent:keeper')).toBe('Keeper');
		expect(whoName('ask')).toBe('Ask');
	});
});

describe('log lines', () => {
	it('says who did what', () => {
		expect(logSentence(entry('gap_opened'))).toBe('Keeper opened a gap');
		expect(logSentence(entry('claim_written', { actor: 'auto' }))).toBe('Keeper wrote a claim');
		expect(logSentence(entry('claim_approved', { actor: 'dana' }))).toBe('dana approved a claim');
		expect(logSentence(entry('claim_queued'))).toBe('Keeper asked a lead to approve a claim');
		expect(logSentence(entry('follow_up_opened', { actor: 'pm' }))).toBe('pm opened a follow-up');
		expect(logSentence(entry('needs_person'))).toBe('Keeper said a gap needs a person');
		expect(logSentence(entry('review_start'))).toBe('Keeper started a review');
		expect(logSentence(entry('review_skipped'))).toBe('Keeper skipped a review');
		expect(logSentence(entry('brand_new_thing'))).toBe('Keeper brand new thing');
	});
	it('names who was consulted', () => {
		expect(logSentence(entry('consulted', { why: 'asked pm' }))).toBe('Keeper asked pm about a gap');
		expect(logSentence(entry('consulted'))).toBe('Keeper asked about a gap');
	});
	it('puts a review reason into words and drops its uid', () => {
		expect(logWhy(entry('review_start', { why: 'review:ab12cd34: manual, budget 3' }))).toBe('on request, budget 3');
		expect(logWhy(entry('review_start', { why: 'review:ab12cd34: build, budget 1' }))).toBe('after a build, budget 1');
		expect(logWhy(entry('review_skipped', { why: 'review:ab12cd34: no_api_key' }))).toBe('no API key');
		expect(logWhy(entry('review_done', { why: 'review:ab12cd34: done' }))).toBeNull();
	});
	it('puts queued reasons into words', () => {
		expect(logWhy(entry('claim_queued', { why: 'high_impact_system, no_source_evidence' }))).toBe(
			'it touches a high-impact system and no commit, PR, ticket or doc is behind it'
		);
	});
	it('keeps any other why as written', () => {
		expect(logWhy(entry('claim_rejected', { why: 'Bob left the team.' }))).toBe('Bob left the team.');
		expect(logWhy(entry('consulted', { why: 'asked pm' }))).toBeNull();
		expect(logWhy(entry('gap_opened'))).toBeNull();
	});
});

describe('checkApproval', () => {
	it('wants a name of 1 to 80 characters once trimmed', () => {
		expect(checkApproval('', '')).toEqual({ by: 'Type your name, so the log says who decided.' });
		expect(checkApproval('   ', '')).toEqual({ by: 'Type your name, so the log says who decided.' });
		expect(checkApproval('x'.repeat(81), '')).toEqual({ by: 'Keep your name to 80 characters.' });
		expect(checkApproval('  Dana  ', '')).toBeNull();
	});
	it('keeps the reason to 500 characters', () => {
		expect(checkApproval('Dana', 'x'.repeat(501))).toEqual({ why: 'Keep the reason to 500 characters.' });
		expect(checkApproval('Dana', `  ${'x'.repeat(500)}  `)).toBeNull();
	});
});

describe('decisionError', () => {
	it('says someone already decided on a 409, whatever the server wrote', () => {
		expect(decisionError(new ApiError(409, 'Claim claim:1 is not waiting for approval: it was decided already.'))).toEqual({
			message: 'Someone already decided this claim. The list now shows where it stands.',
			gone: true
		});
	});
	it("keeps the server's sentence on a 409 while the brain is being rebuilt, and keeps the claim", () => {
		const said = 'The brain is being rebuilt; try again when the build finishes.';
		expect(decisionError(new ApiError(409, said))).toEqual({ message: said });
	});
	it('says the claim is gone on a 404', () => {
		expect(decisionError(new ApiError(404, 'No claim claim:1'))).toEqual({ message: 'This claim is gone. The list now shows the ones still waiting.', gone: true });
	});
	it("keeps the server's sentence when the brain is not there", () => {
		const said = 'The brain of synthetic is not there (brain_synthetic is missing). Build the company, then approve again.';
		expect(decisionError(new ApiError(503, said))).toEqual({ message: said });
		expect(decisionError(new ApiError(503, undefined))).toEqual({
			message: "The company's brain isn't there. Build the company, then approve again."
		});
	});
	it('puts a 422 under the field it names', () => {
		expect(decisionError(new ApiError(422, [{ loc: ['body', 'by'], msg: 'too short' }]))).toEqual({
			field: 'by',
			message: 'Type your name, up to 80 characters.'
		});
		expect(decisionError(new ApiError(422, [{ loc: ['body', 'why'], msg: 'too long' }]))).toEqual({
			field: 'why',
			message: 'Keep the reason to 500 characters.'
		});
	});
	it('falls back to the usual words', () => {
		expect(decisionError(new TypeError('fetch failed')).message).toMatch(/isn't answering/);
	});
});

describe('reviews', () => {
	it('knows when a Keeper review is going', () => {
		expect(keeperRunning([run('ask:t:1', 'ask', 'running')])).toBe(false);
		expect(keeperRunning([run('keeper:review:1', 'keeper', 'done'), run('keeper:review:2', 'keeper', 'running')])).toBe(true);
	});
	it('changes its key when a Keeper run starts, takes a step or ends, not for Ask runs', () => {
		const a = keeperRunsKey([run('ask:t:1', 'ask', 'running'), run('keeper:review:1', 'keeper', 'running')]);
		expect(keeperRunsKey([run('ask:t:1', 'ask', 'done'), run('keeper:review:1', 'keeper', 'running')])).toBe(a);
		expect(keeperRunsKey([run('keeper:review:1', 'keeper', 'done')])).not.toBe(a);
		const stepped = run('keeper:review:1', 'keeper', 'running');
		stepped.steps = [{ n: 1, actor: 'pm', tool: 'work_history', kind: 'graph', input: {}, status: 'running', count: null, error: null, touched: [] }];
		expect(keeperRunsKey([run('ask:t:1', 'ask', 'running'), stepped])).not.toBe(a);
	});
	it('says what Review now did', () => {
		expect(reviewNote(review())).toBeNull();
		expect(reviewNote(review({ state: 'skipped', stop: 'no_api_key' }))).toBe(
			'Review skipped: the API has no Claude key, so the Keeper only rechecked its claims and looked for new gaps.'
		);
		expect(reviewNote(review({ state: 'done', gaps: [] }))).toBe('Review done: no gap was waiting.');
		expect(reviewNote(review({ state: 'done', gaps: ['gap:1', 'gap:2'] }))).toBe('Review done: 2 gaps reviewed.');
		expect(reviewNote(review({ state: 'failed', stop: 'brain_unavailable' }))).toBe("Review failed: the company's brain isn't there.");
		expect(reviewNote(review({ state: 'stopped', stop: null }))).toBe('Review stopped.');
	});
});

describe('logTime', () => {
	const now = Date.parse('2026-10-17T15:00:00');
	it('gives the clock time today and the date before', () => {
		expect(logTime('2026-10-17T14:09:00', now)).toBe('14:09');
		expect(logTime('2026-02-06T09:00:00', now)).toBe('6 Feb');
		expect(logTime('2025-02-06T09:00:00', now)).toBe('6 Feb 2025');
		expect(logTime('not a time', now)).toBe('');
	});
});

describe('evidenceRefs', () => {
	it('names the evidence the map knows, and keeps the rest by uid', () => {
		const known = new Map([['synthetic:pr:31', { label: 'WorkItem', title: 'fix(billing): refunds', url: 'https://x/31' }]]);
		expect(evidenceRefs(['synthetic:pr:31', 'person:bob', 'synthetic:doc:x.md'], (uid) => known.get(uid) ?? null)).toEqual([
			{ uid: 'synthetic:pr:31', label: 'WorkItem', title: 'fix(billing): refunds', url: 'https://x/31' },
			{ uid: 'person:bob', label: 'Person', title: 'bob', url: null },
			{ uid: 'synthetic:doc:x.md', label: null, title: 'doc:x.md', url: null }
		]);
	});
});

describe('railLog', () => {
	it("leaves out the runner's episode lines, which repeat the lines around them", () => {
		const lines = [entry('claim_queued'), entry('episode', { actor: 'agent:keeper' }), entry('consulted'), entry('gap_opened')];
		expect(railLog(lines, 2).map((e) => e.action)).toEqual(['claim_queued', 'consulted']);
	});
});

describe('decidedLine', () => {
	const claim = { statement: 'bob decides the refund rules in Billing.', kind: 'expert' as const, status: 'accepted' as const };
	it('says what an accepted approval did, and the follow-up only for kinds pm follows up', () => {
		expect(decidedLine('approve', 'Dana', claim)).toBe('Dana approved: bob decides the refund rules in Billing. pm opens its follow-up next.');
		expect(decidedLine('approve', 'Dana', { ...claim, kind: 'fact' })).toBe('Dana approved: bob decides the refund rules in Billing.');
	});
	it('says the sources won when the approval found they now say otherwise', () => {
		expect(decidedLine('approve', 'Dana', { ...claim, kind: 'fact', status: 'conflicts_with_source' })).toBe(
			'Dana approved, but the sources now say otherwise, so the brain keeps what they say: bob decides the refund rules in Billing. pm opens a follow-up to fix the source.'
		);
	});
	it("says the gap is open again when the brain didn't have the claim's subject or evidence", () => {
		expect(decidedLine('approve', 'Dana', { ...claim, status: 'stale' })).toBe(
			"Dana approved, but the brain no longer has this claim's subject or evidence, so it was not added: bob decides the refund rules in Billing. Its gap is open again."
		);
	});
	it('says a rejection reopens the gap', () => {
		expect(decidedLine('reject', 'Dana', { ...claim, status: 'rejected' })).toBe('Dana rejected: bob decides the refund rules in Billing. Its gap is open again.');
	});
});

describe('reasonRows', () => {
	it('gives each reason a heading and what it means, in order', () => {
		const rows = reasonRows(['replaces_claim', 'no_source_evidence']);
		expect(rows.map((r) => r.title)).toEqual(['It replaces an earlier claim', 'No source is behind it']);
		expect(rows[1].detail).toMatch(/No commit, PR, ticket or doc/);
	});
	it('reads an unknown code as words, and no reasons as a plain "needs a lead"', () => {
		expect(reasonRows(['new_rule'])).toEqual([{ code: 'new_rule', title: 'new rule', detail: '' }]);
		expect(reasonRows([])[0].title).toBe('It needs a lead');
	});
});

describe('decidedTag', () => {
	it('says what the decision ended as', () => {
		expect(decidedTag('approve', 'accepted')).toEqual({ text: 'Approved', tone: 'success' });
		expect(decidedTag('approve', 'conflicts_with_source').tone).toBe('warning');
		expect(decidedTag('approve', 'stale').text).toBe('Approved, not added');
		expect(decidedTag('reject', 'rejected')).toEqual({ text: 'Rejected', tone: 'neutral' });
	});
});
