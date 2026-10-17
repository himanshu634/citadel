/**
 * Fixed Sources page data for the `/components` gallery: one row per state the ledger can show.
 * Numbers are FalkorDB's and Synthetic Co's as measured on 17 Oct 2026.
 */
import { ledger } from '$lib/sources';
import type { LabelCounts, SourceRow } from '$lib/types';

const base: Omit<SourceRow, 'key' | 'type' | 'location'> = {
	reads: [],
	downloads: false,
	status: 'synced',
	problem: null,
	last_run: '2026-10-16T14:41:52Z',
	records: 3719,
	cursor: '2026-10-16T12:24:57Z',
	window_changed: false
};

export const sampleSources: SourceRow[] = [
	{
		...base,
		key: 'github:FalkorDB/FalkorDB',
		type: 'github',
		location: 'FalkorDB/FalkorDB',
		reads: ['commits', 'pull_requests', 'issues', 'reviews', 'codeowners', 'repo_docs'],
		downloads: true
	},
	{
		...base,
		key: 'canonical_jsonl:apps/brain/examples/synthetic_company',
		type: 'canonical_jsonl',
		location: 'apps/brain/examples/synthetic_company',
		records: 114,
		cursor: '2026-09-11T12:00:00Z',
		window_changed: true
	},
	{
		...base,
		key: 'canonical_jsonl:apps/brain/examples/synthetic_company/tickets',
		type: 'canonical_jsonl',
		location: 'apps/brain/examples/synthetic_company/tickets',
		records: 22,
		cursor: '2026-09-25T12:00:00Z'
	},
	{
		...base,
		key: 'local_docs:data/inbox/falkordb/docs',
		type: 'local_docs',
		location: 'data/inbox/falkordb/docs',
		status: 'skipped',
		problem: 'Folder data/inbox/falkordb/docs does not exist',
		last_run: null,
		records: null,
		cursor: null
	},
	{
		...base,
		key: 'linear:synthetic-co',
		type: 'linear',
		location: 'synthetic-co',
		reads: ['IDN', 'PAY'],
		downloads: true,
		status: 'blocked',
		problem: 'No Linear API key: set LINEAR_API_KEY in .env',
		last_run: null,
		records: null,
		cursor: null
	},
	{
		...base,
		key: 'github:acme-labs-with-a-very-long-organisation-name/an-equally-long-repository-name',
		type: 'github',
		location: 'acme-labs-with-a-very-long-organisation-name/an-equally-long-repository-name',
		downloads: true,
		status: 'never',
		last_run: null,
		records: null,
		cursor: null
	}
];

export const sampleLabels: LabelCounts[] = [
	{
		source: 'github',
		total: 4758,
		kinds: [
			{ label: 'Chunk', kind: null, count: 2735, states: {} },
			{ label: 'WorkItem', kind: 'issue', count: 998, states: { closed: 532, open: 466 } },
			{
				label: 'WorkItem',
				kind: 'pull_request',
				count: 750,
				states: { merged: 323, open: 232, closed: 195 }
			},
			{ label: 'Change', kind: null, count: 259, states: {} },
			{ label: 'Document', kind: null, count: 16, states: {} }
		]
	},
	{
		source: 'derived',
		total: 263,
		kinds: [
			{ label: 'Person', kind: null, count: 191, states: {} },
			{ label: 'System', kind: null, count: 71, states: {} },
			{ label: 'Team', kind: null, count: 1, states: {} }
		]
	},
	{
		source: 'canonical_jsonl',
		total: 94,
		kinds: [
			{ label: 'Chunk', kind: null, count: 35, states: {} },
			{ label: 'Change', kind: null, count: 25, states: {} },
			{ label: 'WorkItem', kind: 'ticket', count: 10, states: { 'In Progress': 3, Todo: 3, Done: 2 } },
			{ label: 'WorkItem', kind: 'pull_request', count: 10, states: { merged: 9, open: 1 } }
		]
	},
	{
		source: 'slack_export',
		total: 2,
		kinds: [{ label: 'WorkItem', kind: 'thread', count: 2, states: { open: 2 } }]
	}
];

export const sampleLedger = ledger(sampleSources, sampleLabels);
export const sampleLocations = new Map(sampleSources.map((s) => [s.key, s.location]));
