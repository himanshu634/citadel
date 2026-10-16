/**
 * What the build page says about a build, as pure functions of its snapshot and events: the
 * header, the title, the progress percentage, the table's merged cells, the log lines and the
 * source names.
 *
 * Why: the backend reports events, not sentences. Keeping the wording and the arithmetic here
 * makes them testable without a browser, and lets the component and the gallery draw the same
 * thing. Stage cells come from `build.ts` (`buildTable`); this file only decides how they read.
 */
import { buildTable, stepOf } from './build';
import type { BuildTable, Cell, SourceRow } from './build';
import type { BuildEvent, BuildSnapshot, BuildStage, BuildState } from './types';

export const isActive = (state: BuildState): boolean => state === 'queued' || state === 'running';

/**
 * Whether `event` is the last one of its build. Same rule as the backend's SSE stream, which
 * closes after such an event: the `done` stage, or any failed or stopped event.
 */
export function endsBuild(event: BuildEvent): boolean {
	return event.stage === 'done' || event.status === 'failed' || event.status === 'stopped';
}

const sameEvent = (a: BuildEvent, b: BuildEvent) =>
	a.at === b.at &&
	a.stage === b.stage &&
	a.status === b.status &&
	a.source === b.source &&
	a.count === b.count &&
	a.message === b.message;

/** The snapshot with `event` added. The same snapshot when it is another company's or a repeat. */
export function withEvent(snapshot: BuildSnapshot, event: BuildEvent): BuildSnapshot {
	if (event.slug !== snapshot.slug || snapshot.events.some((held) => sameEvent(held, event))) {
		return snapshot;
	}
	return { ...snapshot, events: [...snapshot.events, event] };
}

const noun = (snapshot: BuildSnapshot) => (snapshot.kind === 'rebuild' ? 'Rebuild' : 'Build');
const lastStage = (snapshot: BuildSnapshot): BuildStage | null => snapshot.events.at(-1)?.stage ?? null;

/**
 * The line over the table: "Step 2 of 4: records" while running. A rebuild's reset and prepare
 * count as steps, and a rebuild that fetches nothing has no fetch step, so the total comes from
 * the plan (`snapshot.stages`), never a fixed number. `stopping` is a stop the user asked for that
 * the build has not reached yet.
 */
export function headerOf(snapshot: BuildSnapshot, stopping = false): string {
	const stage = lastStage(snapshot);
	const at = stage ? ` at ${stage}` : '';
	switch (snapshot.state) {
		case 'queued':
			return 'Queued, waiting for another build to finish';
		case 'running': {
			if (stopping) return 'Stopping after the current step';
			const step = stepOf({
				kind: snapshot.kind,
				state: snapshot.state,
				stage,
				stages: snapshot.stages,
				started_at: snapshot.started_at
			});
			return step ? `Step ${step.n} of ${step.total}: ${stage}` : 'Building';
		}
		case 'done':
			return `${noun(snapshot)} finished`;
		case 'failed':
			return `${noun(snapshot)} failed${at}`;
		case 'stopped':
			return `${noun(snapshot)} stopped${at}`;
	}
}

/** The page's title: what is happening to the company. */
export function titleOf(name: string, snapshot: BuildSnapshot): string {
	const rebuild = snapshot.kind === 'rebuild';
	switch (snapshot.state) {
		case 'queued':
		case 'running':
			return `${rebuild ? 'Rebuilding' : 'Building'} ${name}`;
		case 'done':
			return `${rebuild ? 'Rebuilt' : 'Built'} ${name}`;
		case 'failed':
			return `${noun(snapshot)} of ${name} failed`;
		case 'stopped':
			return `${noun(snapshot)} of ${name} stopped`;
	}
}

type SourceStage = 'fetch' | 'records' | 'normalize' | 'load';
const SOURCE_STAGES: SourceStage[] = ['fetch', 'records', 'normalize', 'load'];

export interface RowPart {
	/** The columns this part covers, in order. More than one when skipped cells are merged. */
	stages: SourceStage[];
	cell: Cell;
}

/**
 * A source row as the cells to draw. A source whose `records` stage was skipped with a message
 * (a folder that is not there, a type with no adapter) never reaches normalize or load, so its
 * skipped cell and the ones after it become one cell that spans them, saying why. A cell
 * left `waiting` after a skip is not waiting for anything. Failed and stopped rows keep their
 * waiting cells as they are.
 */
export function rowView(row: SourceRow): RowPart[] {
	const cells = SOURCE_STAGES.map((stage) => ({ stage, cell: row[stage] }));
	const skipAt = cells.findIndex(
		({ stage, cell }) => stage !== 'fetch' && cell.status === 'skipped' && cell.message != null
	);
	if (skipAt < 0) return cells.map(({ stage, cell }) => ({ stages: [stage], cell }));

	// The merge starts at the earliest skipped cell that carries the message (a source with no
	// adapter has it on fetch too).
	const message = cells[skipAt].cell.message as string;
	let start = skipAt;
	while (start > 0 && cells[start - 1].cell.status === 'skipped' && cells[start - 1].cell.message === message) {
		start--;
	}
	const rest = cells.slice(start);
	const mergeable = rest.every(({ cell }) => cell.status === 'skipped' || cell.status === 'waiting');
	if (!mergeable) return cells.map(({ stage, cell }) => ({ stages: [stage], cell }));
	return [
		...cells.slice(0, start).map(({ stage, cell }) => ({ stages: [stage], cell })),
		{ stages: rest.map(({ stage }) => stage), cell: { status: 'skipped' as const, message } }
	];
}

const UNITS: Partial<Record<BuildStage, string>> = {
	fetch: 'items',
	records: 'read',
	normalize: 'kept',
	load: 'written'
};
const number = new Intl.NumberFormat('en-US');

/** The small print under a cell's status: its count with a unit, then its message. */
export function cellNote(stage: BuildStage, cell: Cell): string {
	const unit = UNITS[stage];
	const parts: string[] = [];
	if (cell.count != null) parts.push(unit ? `${number.format(cell.count)} ${unit}` : number.format(cell.count));
	if (cell.message != null && cell.message !== '') parts.push(cell.message);
	return parts.join(', ');
}

const finished = (cell: Cell) => cell.status === 'done' || cell.status === 'skipped';

function rawPercent(events: BuildEvent[], stages: BuildStage[]): number {
	const table: BuildTable = buildTable(events, stages);
	let total = table.reset ? 2 : 1; // prepare, and reset in a rebuild
	let done = Number(finished(table.prepare)) + Number(table.reset ? finished(table.reset) : 0);
	// Sources not met yet are unknown: until the first one shows, assume one.
	total += Math.max(table.rows.length, 1) * SOURCE_STAGES.length;
	for (const row of table.rows) {
		for (const { stages: span, cell } of rowView(row)) {
			if (finished(cell)) done += span.length;
		}
	}
	return Math.floor((done / total) * 100);
}

/**
 * How far the build is, 0 to 100. It counts the cells that are done or skipped. A source
 * only exists once it reports, so the total grows as sources appear; to keep the meter from
 * stepping back when one does, the result is the highest value reached by any prefix of the
 * events. It is 100 only for a build that is done.
 */
export function percentOf(snapshot: BuildSnapshot): number {
	if (snapshot.state === 'done') return 100;
	let best = 0;
	for (let n = 1; n <= snapshot.events.length; n++) {
		best = Math.max(best, rawPercent(snapshot.events.slice(0, n), snapshot.stages));
	}
	return Math.min(best, 99);
}

const KNOWN_SOURCES: Record<string, string> = {
	github: 'GitHub',
	local_docs: 'Documents folder',
	canonical_jsonl: 'Canonical JSONL'
};

/** A source key (`github:acme/platform`) as a name and the part after the type. */
export function sourceLabel(key: string): { name: string; detail: string } {
	const colon = key.indexOf(':');
	const type = colon < 0 ? key : key.slice(0, colon);
	const detail = colon < 0 ? '' : key.slice(colon + 1);
	const words = type.replaceAll('_', ' ');
	return { name: KNOWN_SOURCES[type] ?? words.charAt(0).toUpperCase() + words.slice(1), detail };
}

export interface LogLine {
	time: string;
	stage: BuildStage;
	status: BuildEvent['status'];
	source: string;
	detail: string;
}

const two = (n: number) => String(n).padStart(2, '0');

/** One event as the log's columns: local HH:MM:SS, stage, status, source and count or message. */
export function logLine(event: BuildEvent): LogLine {
	const at = new Date(event.at);
	const time = Number.isNaN(at.getTime())
		? ''
		: `${two(at.getHours())}:${two(at.getMinutes())}:${two(at.getSeconds())}`;
	return {
		time,
		stage: event.stage,
		status: event.status,
		source: event.source?.replace(':', ' ') ?? '',
		detail: cellNote(event.stage, {
			status: event.status,
			...(event.count != null && { count: event.count }),
			...(event.message != null && { message: event.message })
		})
	};
}
