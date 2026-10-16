/**
 * Build progress helpers: turn the pipeline's event stream into the stage table the build page
 * draws, and a snapshot's stage into "step n of N".
 *
 * Why: the backend sends events (one per stage change, per source); the UI wants one cell per
 * source and stage. Folding is pure, so it is tested here and the same code serves the live stream
 * and a finished build read from disk.
 */
import type { BuildEvent, BuildStage, BuildStatus, BuildSummary } from './types';

export interface Cell {
	status: BuildStatus;
	count?: number;
	message?: string;
}

export interface SourceRow {
	source: string;
	fetch: Cell;
	records: Cell;
	normalize: Cell;
	load: Cell;
}

export interface BuildTable {
	prepare: Cell;
	/** Only a rebuild resets the graph first. */
	reset?: Cell;
	rows: SourceRow[];
}

const SOURCE_STAGES = ['fetch', 'records', 'normalize', 'load'] as const;
type SourceStage = (typeof SOURCE_STAGES)[number];

function cellOf(event: BuildEvent): Cell {
	const cell: Cell = { status: event.status };
	if (event.count != null) cell.count = event.count;
	if (event.message != null) cell.message = event.message;
	return cell;
}

/**
 * The latest event of each (source, stage) becomes that cell; a cell nothing has reported is
 * `waiting`. `stages` is the plan (`BuildSnapshot.stages`): without a `reset` stage the table has
 * no reset cell, and when the plan has no `fetch` (a rebuild that downloads nothing) the fetch
 * cells nothing reported are `skipped` without a message, because nothing will ever run there. An
 * event always wins over the plan. Without `stages`, nothing is assumed beyond the events.
 */
export function buildTable(events: BuildEvent[], stages?: BuildStage[]): BuildTable {
	const company = new Map<'prepare' | 'reset', Cell>();
	const bySource = new Map<string, Partial<Record<SourceStage, Cell>>>();

	for (const event of events) {
		if (event.stage === 'prepare' || event.stage === 'reset') {
			company.set(event.stage, cellOf(event));
		} else if (event.source != null && (SOURCE_STAGES as readonly string[]).includes(event.stage)) {
			const cells = bySource.get(event.source) ?? {};
			cells[event.stage as SourceStage] = cellOf(event);
			bySource.set(event.source, cells);
		}
	}

	const fetchUnplanned: Cell | undefined =
		stages && !stages.includes('fetch') ? { status: 'skipped' } : undefined;
	const waiting = (): Cell => ({ status: 'waiting' });

	const table: BuildTable = {
		prepare: company.get('prepare') ?? waiting(),
		rows: [...bySource].map(([source, cells]) => ({
			source,
			fetch: cells.fetch ?? (fetchUnplanned ? { ...fetchUnplanned } : waiting()),
			records: cells.records ?? waiting(),
			normalize: cells.normalize ?? waiting(),
			load: cells.load ?? waiting()
		}))
	};
	const reset = company.get('reset') ?? (stages?.includes('reset') ? waiting() : undefined);
	if (reset) table.reset = reset;
	return table;
}

/**
 * "Building, step n of N": n is the 1-based place of the build's current stage among its planned
 * stages, N their number, both without the closing `done`. Null when no build is active or the
 * stage is not (yet) one of the planned ones.
 */
export function stepOf(summary: BuildSummary): { n: number; total: number } | null {
	if (summary.state !== 'queued' && summary.state !== 'running') return null;
	if (summary.stage == null) return null;
	const planned: BuildStage[] = summary.stages.filter((s) => s !== 'done');
	const index = planned.indexOf(summary.stage);
	return index < 0 ? null : { n: index + 1, total: planned.length };
}
