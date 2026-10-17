// Example chats for the gallery: the chat list's states and one answer's timeline, with an MCP call.
import type { AskLlmEvent, ModelInfo, ThreadSummary } from '$lib/types';
import { done } from './walk-samples';

export const NOW = Date.parse('2026-10-16T12:00:00Z');

const chat = (id: string, title: string, minutesAgo: number, turns: number, last_status: ThreadSummary['last_status']): ThreadSummary => {
	const at = new Date(NOW - minutesAgo * 60_000).toISOString();
	return { id, title, created_at: at, updated_at: at, turns, last_status };
};

export const chats: ThreadSummary[] = [
	chat('c1', 'Who does Alice work with?', 0, 1, 'running'),
	chat('c2', 'Which systems usually change together?', 12, 3, 'done'),
	chat('c3', 'Where do the declared owners differ from who does the work on Web app?', 190, 2, 'stopped'),
	chat('c4', 'Why did we move sessions to JWT?', 60 * 50, 1, 'failed'),
	chat('c5', 'Who reviews billing PRs?', 60 * 24 * 12, 4, 'done')
];

const usage = { input: 1200, output: 180, cache_read: 4400, cache_write: 0 };

export const timeline: AskLlmEvent[] = [
	{
		seq: 1,
		text: "I'll start with Alice's profile, then see who else works on Auth.",
		thinking: 'The question is about collaboration. Profile first, then experts for her main system.',
		model: 'claude-haiku-5-5',
		stop: 'tool_use',
		ms: 1540,
		usage,
		calls: [
			{ id: 's1', tool: 'person_profile', kind: 'graph', server: null, input: { login: 'alice' } },
			{ id: 's2', tool: 'experts_for_system', kind: 'graph', server: null, input: { system: 'Auth' } },
			{
				id: 'm1',
				tool: 'search_handbook',
				kind: 'mcp',
				server: 'handbook',
				input: { query: 'identity team pairing' },
				error: null,
				result: 'Identity team: Alice and Carol pair on token work (handbook/teams.md).'
			}
		]
	},
	{
		seq: 2,
		text: null,
		thinking: null,
		model: 'claude-haiku-5-5',
		stop: 'tool_use',
		ms: 980,
		usage,
		calls: [{ id: 's3', tool: 'path_between', kind: 'graph', server: null, input: { from_uid: 'person:alice', to_uid: 'person:carol' } }]
	},
	{
		seq: 3,
		text: null,
		thinking: null,
		model: 'claude-haiku-5-5',
		stop: 'tool_use',
		ms: 2210,
		usage,
		calls: [{ id: 's9', tool: 'submit_answer', kind: 'submit', server: null, input: {} }]
	}
];

export const timelineSteps = done;

/** GET /api/models as the backend serves it (agents/llm.py MODELS). */
export const models: ModelInfo[] = [
	{ id: 'claude-haiku-5-5', name: 'Haiku 5.5', blurb: 'Fastest. Lookups and short walks.', cost: 1, slow: false },
	{ id: 'claude-sonnet-5-5', name: 'Sonnet 5.5', blurb: 'Balanced. Longer walks across teams.', cost: 20, slow: false },
	{ id: 'claude-opus-5-5', name: 'Opus 5.5', blurb: 'Most careful over many hops.', cost: 40, slow: false },
	{ id: 'claude-fable-5-1', name: 'Fable 5.1', blurb: 'Most capable. Can take minutes.', cost: 100, slow: true }
];
