/**
 * What the Sources page (design direction A, the source ledger) says about each source.
 *
 * Why: the API returns raw facts (status, sync record, node counts per `source` label). Turning
 * them into words, and deciding which counts belong to which row, lives here once, so the page
 * and the gallery cannot drift and the rules are tested. The rules that matter:
 * - Node counts are per label, not per configured source: two folders of one type write the same
 *   label, so they share one count and each row says so.
 * - A label no configured type writes (a JSONL record's own `slack_export`) is counted with the
 *   JSONL sources, which are the only ones that can write such labels; with no JSONL source it
 *   gets a row of its own.
 * - `derived` (people, teams, systems made from links) is never credited to a source.
 */
import type { KindCount, LabelCounts, NodeType, SourceRow, SourceStatus } from './types';

const TITLES: Record<string, string> = {
	github: 'GitHub',
	linear: 'Linear',
	local_docs: 'Documents folder',
	canonical_jsonl: 'JSONL records'
};

/** The source type's name as people say it. */
export function sourceTitle(type: string): string {
	return TITLES[type] ?? type;
}

export interface StatusWord {
	word: string;
	tone: 'success' | 'neutral' | 'warning' | 'danger';
}

const STATUS: Record<SourceStatus, StatusWord> = {
	synced: { word: 'Synced', tone: 'success' },
	never: { word: 'Not synced yet', tone: 'neutral' },
	skipped: { word: 'Skipped', tone: 'warning' },
	blocked: { word: 'Stops the build', tone: 'danger' }
};

export function statusWord(status: SourceStatus): StatusWord {
	return STATUS[status];
}

/** `16 Oct, 20:11` in local time; the year is added when it is not this year. */
export function when(iso: string | null, now = new Date()): string | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	const day = date.toLocaleDateString('en-GB', {
		day: 'numeric',
		month: 'short',
		...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' })
	});
	const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
	return `${day}, ${time}`;
}

export interface Credit {
	/** The label groups counted on this row, the source's own type first. */
	groups: LabelCounts[];
	total: number;
	/** Other configured sources whose nodes are in the same count (same type). */
	sharedWith: string[];
	/** Labels a record chose itself (not the type), counted here: `slack_export`. */
	extraLabels: string[];
}

export interface Ledger {
	/** By source key. */
	credits: Map<string, Credit>;
	/** People, teams and systems made from links. */
	derived: LabelCounts | null;
	/** Labels no configured source can have written, when no JSONL source takes them. */
	other: LabelCounts[];
}

const DERIVED = 'derived';
const JSONL = 'canonical_jsonl';

/** Which counts each row shows (rules in the module comment). */
export function ledger(sources: SourceRow[], labels: LabelCounts[]): Ledger {
	const types = new Set(sources.map((s) => s.type));
	const byLabel = new Map(labels.map((g) => [g.source, g]));
	const loose = labels.filter((g) => g.source !== DERIVED && !types.has(g.source));
	const credits = new Map<string, Credit>();
	for (const s of sources) {
		const own = byLabel.get(s.type);
		const extra = s.type === JSONL ? loose : [];
		const groups = [...(own ? [own] : []), ...extra];
		credits.set(s.key, {
			groups,
			total: groups.reduce((n, g) => n + g.total, 0),
			sharedWith: sources.filter((o) => o.type === s.type && o.key !== s.key).map((o) => o.key),
			extraLabels: extra.map((g) => g.source)
		});
	}
	return {
		credits,
		derived: byLabel.get(DERIVED) ?? null,
		other: types.has(JSONL) ? [] : loose
	};
}

export interface KindLine {
	name: string;
	/** Node colour for the mark; null for text pieces (no node kind of their own on the map). */
	type: NodeType | null;
	count: number;
	/** States, most first: `466 open, 532 closed`. Empty when the kind has none. */
	detail: string;
}

const WORK_KINDS: Record<string, string> = {
	pull_request: 'Pull requests',
	issue: 'Issues',
	ticket: 'Tickets',
	thread: 'Threads'
};

const LABELS: Record<string, [name: string, type: NodeType | null]> = {
	Change: ['Commits', 'change'],
	Document: ['Docs', 'document'],
	Chunk: ['Comment text, in pieces', null],
	Person: ['People', 'person'],
	Team: ['Teams', 'team'],
	System: ['Systems', 'system']
};

function states(kind: KindCount): string {
	return Object.entries(kind.states)
		.sort((a, b) => b[1] - a[1])
		.map(([state, n]) => `${n.toLocaleString('en-GB')} ${state.toLowerCase()}`)
		.join(', ');
}

/** One line per node kind across the groups, biggest first; same kinds are added up. */
export function kindLines(groups: LabelCounts[]): KindLine[] {
	const lines = new Map<string, KindLine & { states: Record<string, number> }>();
	for (const kind of groups.flatMap((g) => g.kinds)) {
		const [name, type] =
			kind.label === 'WorkItem'
				? [WORK_KINDS[kind.kind ?? ''] ?? `Work items (${kind.kind ?? 'other'})`, 'work-item' as const]
				: (LABELS[kind.label] ?? [kind.label, null]);
		const line = lines.get(name) ?? { name, type, count: 0, detail: '', states: {} };
		line.count += kind.count;
		for (const [state, n] of Object.entries(kind.states)) {
			line.states[state] = (line.states[state] ?? 0) + n;
		}
		lines.set(name, line);
	}
	return [...lines.values()]
		.map(({ states: s, ...line }) => ({
			...line,
			detail: states({ label: '', kind: null, count: line.count, states: s })
		}))
		.sort((a, b) => b.count - a.count);
}

/** A short list of what the counts hold: `1,748 work items, 259 commits, 16 docs`. */
export function creditSummary(lines: KindLine[], limit = 3): string {
	const work = lines.filter((l) => l.type === 'work-item').reduce((n, l) => n + l.count, 0);
	const parts: [number, string][] = [];
	if (work) parts.push([work, work === 1 ? 'work item' : 'work items']);
	for (const l of lines) {
		if (l.type === 'work-item') continue;
		parts.push([l.count, l.type === null ? 'comment pieces' : l.name.toLowerCase()]);
	}
	return parts
		.slice(0, limit)
		.map(([n, what]) => `${n.toLocaleString('en-GB')} ${what}`)
		.join(', ');
}

export interface Summary {
	tone: 'danger' | 'warning';
	title: string;
	body: string;
}

/** The banner over the ledger: a blocked source first (every build fails), then skipped ones. */
export function summary(sources: SourceRow[]): Summary | null {
	const blocked = sources.filter((s) => s.status === 'blocked');
	const skipped = sources.filter((s) => s.status === 'skipped');
	if (blocked.length) {
		const n = blocked.length;
		return {
			tone: 'danger',
			title: n === 1 ? 'Every sync fails until 1 source is fixed' : `Every sync fails until ${n} sources are fixed`,
			body: `${blocked.map((s) => sourceTitle(s.type)).join(' and ')} cannot download. Fix it, or remove the source in Settings.`
		};
	}
	if (skipped.length) {
		const n = skipped.length;
		return {
			tone: 'warning',
			title: n === 1 ? '1 source loads nothing' : `${n} sources load nothing`,
			body:
				n === 1
					? 'The last build skipped it. The row says why.'
					: 'Builds skip them. Each row says why.'
		};
	}
	return null;
}

/** The page's one-line description: `3 sources in the config, 1 synced.` */
export function headline(sources: SourceRow[]): string {
	const n = sources.length;
	if (n === 0) return 'No sources in the config yet.';
	const synced = sources.filter((s) => s.status === 'synced').length;
	const total = n === 1 ? '1 source in the config' : `${n} sources in the config`;
	if (synced === 0) return `${total}, none synced yet.`;
	return `${total}, ${synced === n && n > 1 ? 'all' : synced} synced.`;
}
