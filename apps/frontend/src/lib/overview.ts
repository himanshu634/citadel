/**
 * What the overview page draws, as pure functions of the API's answers: which of its states a
 * company is in, the title of the "waiting" banner, and the rows and cards mapped from `Overview`.
 *
 * Why: the page has many states and the API's rows are not the components' props. Keeping both
 * decisions here makes them testable, and keeps the page a thin layer of fetch and markup. The
 * state comes from `company.status`, never from `build`, which may be a finished build.
 */
import { buildingLabel } from './topbar';
import { NODE_PLURALS } from './types';
import type {
	Company,
	NodeType,
	PersonActivity,
	RecentWorkItem,
	Stat,
	SystemSummary,
	WorkItem
} from './types';

export type OverviewView =
	/**
	 * The graph holds data: fetch the overview. `failure` is the last build's error, if it failed;
	 * `building` is a rebuild or sync running over a graph that already has data (the banner says so).
	 */
	| { kind: 'data'; failure: string | null; building: boolean }
	/** Nothing is loaded yet: the first build is running or has never run. No overview fetch. */
	| { kind: 'waiting' }
	| { kind: 'invalid'; error: string }
	/** FalkorDB did not answer: no overview fetch. */
	| { kind: 'unreachable' };

export function viewOf(company: Company): OverviewView {
	switch (company.status) {
		case 'invalid':
			return { kind: 'invalid', error: company.error ?? 'The config file could not be read.' };
		case 'unknown':
			return { kind: 'unreachable' };
		case 'empty':
			return { kind: 'waiting' };
		case 'building':
			// `last_synced_at` stays set during a build (spec 6.1): a graph that was loaded before still
			// has an overview to show; only a company that never finished a load waits.
			return company.last_synced_at
				? { kind: 'data', failure: null, building: true }
				: { kind: 'waiting' };
		case 'failed':
			return { kind: 'data', failure: company.error ?? 'The last build failed.', building: false };
		default:
			return { kind: 'data', failure: null, building: false };
	}
}

/** The waiting banner's title: "Building, step 3 of 5", "Building", or "Not built yet". */
export function buildingTitle(company: Company): string {
	return company.status === 'building' ? buildingLabel(company) : 'Not built yet';
}

/** The graph labels the overview counts, in display order. Other labels (Chunk) stay out. */
const LABELS: [label: string, type: NodeType][] = [
	['Person', 'person'],
	['Team', 'team'],
	['System', 'system'],
	['WorkItem', 'work-item'],
	['Change', 'change'],
	['Document', 'document']
];

export interface StatCard {
	type: NodeType;
	label: string;
	value: number;
}

export function statCards(counts: Stat[]): StatCard[] {
	const cards: StatCard[] = [];
	for (const [label, type] of LABELS) {
		const found = counts.find((s) => s.type === label);
		if (found) cards.push({ type, label: NODE_PLURALS[type], value: found.count });
	}
	return cards;
}

export function workItemOf(item: RecentWorkItem): WorkItem {
	const out: WorkItem = {
		uid: item.uid,
		kind: item.kind as WorkItem['kind'],
		title: item.title,
		state: item.state
	};
	if (item.number != null) out.number = item.number;
	if (item.author != null) out.author = item.author;
	if (item.last_at != null) out.date = item.last_at;
	if (item.systems.length > 0) out.system = item.systems.join(', ');
	return out;
}

export function systemBars(systems: SystemSummary[]) {
	return systems.map((s) => ({
		label: s.system,
		value: s.changes,
		meta: s.owners.length > 0 ? s.owners.join(', ') : 'no owner'
	}));
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;

export function peopleRows(people: PersonActivity[]) {
	return people.map((p) => ({
		key: p.person_uid,
		name: p.display_name ?? p.login,
		meta: [...p.teams, plural(p.prs, 'PR'), plural(p.reviews, 'review')].join(', ')
	}));
}

/** "1 Jan 2026" for the window's start date (a calendar date, so no time-zone shift). */
export function sinceLabel(iso: string): string {
	const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
	if (!match) return iso;
	const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
	return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
