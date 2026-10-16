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
	/**
	 * How the build ended when the failure or stop belongs to no source: the backend closes a job
	 * that failed or stopped between sources with a source-less event on a source stage.
	 */
	closing?: { stage: BuildStage; status: BuildStatus; message?: string };
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
 *
 * A source whose fetch cell nothing reported but which has a later-stage event is `skipped` too:
 * a partial refetch fetches only the changed sources, the others go straight to records.
 *
 * A source-less `failed`/`stopped` event on a source stage (the job ended between sources) becomes
 * `closing`, and the cells of that stage still `waiting` or `running` take its status, so no cell
 * keeps running after the build ended.
 */
export function buildTable(events: BuildEvent[], stages?: BuildStage[]): BuildTable {
	const company = new Map<'prepare' | 'reset', Cell>();
	const bySource = new Map<string, Partial<Record<SourceStage, Cell>>>();
	let closing: BuildTable['closing'];

	for (const event of events) {
		if (event.stage === 'prepare' || event.stage === 'reset') {
			company.set(event.stage, cellOf(event));
		} else if (event.source != null && (SOURCE_STAGES as readonly string[]).includes(event.stage)) {
			const cells = bySource.get(event.source) ?? {};
			cells[event.stage as SourceStage] = cellOf(event);
			bySource.set(event.source, cells);
		} else if (
			event.source == null &&
			(SOURCE_STAGES as readonly string[]).includes(event.stage) &&
			(event.status === 'failed' || event.status === 'stopped')
		) {
			closing = { stage: event.stage, status: event.status };
			if (event.message != null) closing.message = event.message;
		}
	}

	const fetchUnplanned = Boolean(stages && !stages.includes('fetch'));
	const waiting = (): Cell => ({ status: 'waiting' });

	const table: BuildTable = {
		prepare: company.get('prepare') ?? waiting(),
		rows: [...bySource].map(([source, cells]) => {
			const reachedIngest = Boolean(cells.records || cells.normalize || cells.load);
			const unfetched: Cell = fetchUnplanned || reachedIngest ? { status: 'skipped' } : waiting();
			return {
				source,
				fetch: cells.fetch ?? unfetched,
				records: cells.records ?? waiting(),
				normalize: cells.normalize ?? waiting(),
				load: cells.load ?? waiting()
			};
		})
	};
	if (closing) {
		table.closing = closing;
		const { stage, status } = closing;
		for (const row of table.rows) {
			const cell = row[stage as SourceStage];
			if (cell.status === 'waiting' || cell.status === 'running') cell.status = status;
		}
	}
	const reset = company.get('reset') ?? (stages?.includes('reset') ? waiting() : undefined);
	if (reset) table.reset = reset;
	return table;
}

/**
 * "Building, step n of N" while a build is active, else null. The backend counts the steps
 * (`step` of `steps`, every source's stages included), so the number never goes back when the
 * second source starts its records. Only a summary without a count (an old build file) falls back
 * to the 1-based place of the current stage among the planned stages, without `done`.
 */
export function stepOf(summary: BuildSummary): { n: number; total: number } | null {
	if (summary.state !== 'queued' && summary.state !== 'running') return null;
	if (summary.steps != null) {
		return summary.step != null ? { n: summary.step, total: summary.steps } : null;
	}
	if (summary.stage == null) return null;
	const planned: BuildStage[] = summary.stages.filter((s) => s !== 'done');
	const index = planned.indexOf(summary.stage);
	return index < 0 ? null : { n: index + 1, total: planned.length };
}
