import { describe, expect, it } from 'vitest';
import {
	creditSummary,
	headline,
	kindLines,
	ledger,
	sourceTitle,
	statusWord,
	summary,
	when
} from './sources';
import type { LabelCounts, SourceRow } from './types';

function row(over: Partial<SourceRow>): SourceRow {
	return {
		key: 'github:FalkorDB/FalkorDB',
		type: 'github',
		location: 'FalkorDB/FalkorDB',
		reads: [],
		downloads: true,
		status: 'synced',
		problem: null,
		last_run: '2026-10-16T14:41:52Z',
		records: 3719,
		cursor: '2026-10-16T12:24:57Z',
		window_changed: false,
		...over
	};
}

const github: LabelCounts = {
	source: 'github',
	total: 1757,
	kinds: [
		{ label: 'WorkItem', kind: 'issue', count: 998, states: { open: 466, closed: 532 } },
		{ label: 'WorkItem', kind: 'pull_request', count: 750, states: { merged: 323, open: 232, closed: 195 } },
		{ label: 'Document', kind: null, count: 9, states: {} }
	]
};
const jsonl: LabelCounts = {
	source: 'canonical_jsonl',
	total: 30,
	kinds: [{ label: 'Change', kind: null, count: 30, states: {} }]
};
const slack: LabelCounts = {
	source: 'slack_export',
	total: 2,
	kinds: [{ label: 'WorkItem', kind: 'thread', count: 2, states: { open: 2 } }]
};
const derived: LabelCounts = {
	source: 'derived',
	total: 263,
	kinds: [{ label: 'Person', kind: null, count: 191, states: {} }]
};

describe('ledger', () => {
	it('credits a source with its own label and never with derived', () => {
		const out = ledger([row({})], [github, derived]);
		const credit = out.credits.get('github:FalkorDB/FalkorDB')!;
		expect(credit.total).toBe(1757);
		expect(credit.sharedWith).toEqual([]);
		expect(out.derived).toBe(derived);
		expect(out.other).toEqual([]);
	});

	it('says when two folders of one type share a count', () => {
		const a = row({ key: 'canonical_jsonl:a', type: 'canonical_jsonl' });
		const b = row({ key: 'canonical_jsonl:b', type: 'canonical_jsonl' });
		const out = ledger([a, b], [jsonl, slack]);
		expect(out.credits.get('canonical_jsonl:a')!.sharedWith).toEqual(['canonical_jsonl:b']);
		expect(out.credits.get('canonical_jsonl:b')!.sharedWith).toEqual(['canonical_jsonl:a']);
	});

	it('counts a label a JSONL record chose with the JSONL sources', () => {
		const a = row({ key: 'canonical_jsonl:a', type: 'canonical_jsonl' });
		const credit = ledger([a], [jsonl, slack]).credits.get('canonical_jsonl:a')!;
		expect(credit.total).toBe(32);
		expect(credit.extraLabels).toEqual(['slack_export']);
	});

	it('gives loose labels their own row when no JSONL source can take them', () => {
		const out = ledger([row({})], [github, slack]);
		expect(out.other).toEqual([slack]);
		expect(out.credits.get('github:FalkorDB/FalkorDB')!.extraLabels).toEqual([]);
	});

	it('gives a source with nothing loaded no groups', () => {
		const docs = row({ key: 'local_docs:d', type: 'local_docs', status: 'skipped' });
		expect(ledger([docs], [github]).credits.get('local_docs:d')).toMatchObject({
			groups: [],
			total: 0
		});
	});
});

describe('kindLines', () => {
	it('names kinds, adds up states and sorts biggest first', () => {
		const lines = kindLines([github]);
		expect(lines.map((l) => l.name)).toEqual(['Issues', 'Pull requests', 'Docs']);
		expect(lines[0]).toMatchObject({ type: 'work-item', count: 998, detail: '532 closed, 466 open' });
		expect(lines[1].detail).toBe('323 merged, 232 open, 195 closed');
		expect(lines[2]).toMatchObject({ type: 'document', detail: '' });
	});

	it('adds the same kind across groups', () => {
		const more: LabelCounts = { ...slack, source: 'x', kinds: [{ ...slack.kinds[0], count: 3, states: { open: 3 } }] };
		const [threads] = kindLines([slack, more]);
		expect(threads).toMatchObject({ name: 'Threads', count: 5, detail: '5 open' });
	});

	it('marks comment pieces as having no node colour', () => {
		const chunks: LabelCounts = { source: 'github', total: 4, kinds: [{ label: 'Chunk', kind: null, count: 4, states: {} }] };
		expect(kindLines([chunks])[0]).toMatchObject({ type: null, name: 'Comment text, in pieces' });
	});
});

describe('creditSummary', () => {
	it('puts work items together, then the biggest other kinds', () => {
		const chunks = { label: 'Chunk', kind: null, count: 2735, states: {} };
		const lines = kindLines([{ ...github, kinds: [...github.kinds, chunks] }]);
		expect(creditSummary(lines)).toBe('1,748 work items, 2,735 comment pieces, 9 docs');
	});
});

describe('summary', () => {
	it('puts a blocked source before skipped ones', () => {
		const out = summary([
			row({ status: 'skipped', type: 'local_docs' }),
			row({ status: 'blocked', type: 'linear' })
		]);
		expect(out).toMatchObject({ tone: 'danger', title: 'Every sync fails until 1 source is fixed' });
		expect(out!.body).toContain('Linear');
	});

	it('counts skipped sources', () => {
		const out = summary([row({ status: 'skipped' }), row({ status: 'skipped' }), row({})]);
		expect(out).toMatchObject({ tone: 'warning', title: '2 sources load nothing' });
	});

	it('is quiet when every source is fine', () => {
		expect(summary([row({}), row({ status: 'never' })])).toBeNull();
	});
});

describe('words', () => {
	it('names types and statuses', () => {
		expect(sourceTitle('local_docs')).toBe('Documents folder');
		expect(sourceTitle('custom')).toBe('custom');
		expect(statusWord('blocked')).toEqual({ word: 'Stops the build', tone: 'danger' });
	});

	it('writes the headline', () => {
		expect(headline([])).toBe('No sources in the config yet.');
		expect(headline([row({}), row({ status: 'skipped' }), row({ status: 'skipped' })])).toBe(
			'3 sources in the config, 1 synced.'
		);
		expect(headline([row({}), row({})])).toBe('2 sources in the config, all synced.');
		expect(headline([row({ status: 'never' })])).toBe('1 source in the config, none synced yet.');
	});

	it('formats times, with the year only when it is not this year', () => {
		const now = new Date(2026, 9, 17);
		expect(when(null, now)).toBeNull();
		expect(when('2026-10-16T14:41:00', now)).toBe('16 Oct, 14:41');
		expect(when('2025-01-02T08:05:00', now)).toBe('2 Jan 2025, 08:05');
	});
});
