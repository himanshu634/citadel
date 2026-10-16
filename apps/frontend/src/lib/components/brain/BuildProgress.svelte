<!--
@component
One build of one company: the step it is on, a progress meter, a table with a cell per source and
stage (Prepare, and Reset in a rebuild, above the sources), and the plain log of every event.
Every cell and the badge pair an icon with a word, so state is never colour alone. It draws only
the snapshot it is given; the page feeds it live and passes the buttons in `actions`.
-->
<script lang="ts">
	import {
		Check,
		Circle,
		CircleAlert,
		CircleMinus,
		Clock,
		LoaderCircle,
		OctagonX
	} from '@lucide/svelte';
	import type { Component, Snippet } from 'svelte';
	import { Badge, Banner } from '$lib';
	import { buildTable } from '$lib/build';
	import type { Cell } from '$lib/build';
	import { cellNote, headerOf, logLine, percentOf, rowView, sourceLabel } from '$lib/buildProgress';
	import type { BuildSnapshot, BuildStage, BuildStatus } from '$lib/types';

	type Props = {
		snapshot: BuildSnapshot;
		/** A stop was asked for and the build has not reached it yet. */
		stopping?: boolean;
		/** The buttons under the log: stop, go to the company, retry. */
		actions?: Snippet;
	};

	let { snapshot, stopping = false, actions }: Props = $props();

	const headingId = $props.id();
	const table = $derived(buildTable(snapshot.events, snapshot.stages));
	const header = $derived(headerOf(snapshot, stopping));
	const percent = $derived(percentOf(snapshot));
	const lines = $derived(snapshot.events.map(logLine));
	const closing = $derived(table.closing);

	const CELL: Record<BuildStatus, { word: string; icon: Component }> = {
		waiting: { word: 'Waiting', icon: Circle },
		running: { word: 'Running', icon: LoaderCircle },
		done: { word: 'Done', icon: Check },
		skipped: { word: 'Skipped', icon: CircleMinus },
		failed: { word: 'Failed', icon: CircleAlert },
		stopped: { word: 'Stopped', icon: OctagonX }
	};

	const BADGE = $derived.by(() => {
		switch (snapshot.state) {
			case 'queued':
				return { tone: 'neutral', word: 'Queued', icon: Clock } as const;
			case 'running':
				return { tone: 'warning', word: stopping ? 'Stopping' : 'Building', icon: LoaderCircle } as const;
			case 'done':
				return { tone: 'success', word: 'Done', icon: Check } as const;
			case 'failed':
				return { tone: 'danger', word: 'Failed', icon: CircleAlert } as const;
			case 'stopped':
				return { tone: 'neutral', word: 'Stopped', icon: OctagonX } as const;
		}
	});
	const BadgeIcon = $derived(BADGE.icon);

	const COLUMNS: { stage: BuildStage; label: string }[] = [
		{ stage: 'fetch', label: 'Fetch' },
		{ stage: 'records', label: 'Records' },
		{ stage: 'normalize', label: 'Normalize' },
		{ stage: 'load', label: 'Load' }
	];

	// Follow the newest line, unless the reader scrolled up to read an older one.
	let pinned = true;
	function onscroll(event: Event & { currentTarget: HTMLElement }) {
		const log = event.currentTarget;
		pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
	}
	function follow(log: HTMLElement) {
		$effect(() => {
			void lines.length;
			if (pinned) log.scrollTop = log.scrollHeight;
		});
	}
</script>

{#snippet status(cell: Cell, stage: BuildStage)}
	{@const view = CELL[cell.status]}
	{@const note = cellNote(stage, cell)}
	{@const Icon = view.icon}
	<span class={['stage', cell.status]}>
		<Icon class={cell.status === 'running' ? 'spin' : undefined} aria-hidden="true" />{view.word}
	</span>
	{#if note}<span class="sub">{note}</span>{/if}
{/snippet}

<section class="panel" aria-labelledby={headingId}>
	<div class="top">
		<div class="head">
			<h2 id={headingId}>{header}</h2>
			<Badge tone={BADGE.tone}>
				<span class="mark"><BadgeIcon class={snapshot.state === 'running' ? 'spin' : undefined} aria-hidden="true" /></span>{BADGE.word}
			</Badge>
		</div>
		<div
			class="meter"
			role="progressbar"
			aria-label="Build progress"
			aria-valuenow={percent}
			aria-valuemin={0}
			aria-valuemax={100}
		>
			<div style:width="{percent}%"></div>
		</div>
	</div>

	{#if snapshot.error}
		<Banner tone="danger" title="Why it failed">{snapshot.error}</Banner>
	{/if}

	<!-- A scrollable region must take focus, or a keyboard cannot reach its far columns. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div class="scroll" role="region" aria-label="Build stages" tabindex="0">
		<table>
			<thead>
				<tr>
					<th scope="col">Source</th>
					{#each COLUMNS as column (column.stage)}
						<th scope="col">{column.label}</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#if table.reset}
					<tr>
						<th scope="row"><b>Reset</b><span class="sub">Clear the graph first</span></th>
						<td colspan={COLUMNS.length}>{@render status(table.reset, 'reset')}</td>
					</tr>
				{/if}
				<tr>
					<th scope="row"><b>Prepare</b><span class="sub">Graph and indexes</span></th>
					<td colspan={COLUMNS.length}>{@render status(table.prepare, 'prepare')}</td>
				</tr>
				{#each table.rows as row (row.source)}
					{@const label = sourceLabel(row.source)}
					<tr>
						<th scope="row">
							<b>{label.name}</b>
							{#if label.detail}<code>{label.detail}</code>{/if}
						</th>
						{#each rowView(row) as part (part.stages[0])}
							<td colspan={part.stages.length}>{@render status(part.cell, part.stages[0])}</td>
						{/each}
					</tr>
				{:else}
					<tr>
						<td colspan={COLUMNS.length + 1} class="none">Sources appear here as they start.</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if closing}
		<p class={['closing', closing.status]}>
			{#if closing.status === 'failed'}<CircleAlert aria-hidden="true" />{:else}<OctagonX aria-hidden="true" />{/if}
			<span>
				{closing.status === 'failed' ? 'Failed' : 'Stopped'} during {closing.stage}{#if closing.message && closing.message !== snapshot.error}: {closing.message}{/if}
			</span>
		</p>
	{/if}

	<div class="log-wrap">
		<h3 id="{headingId}-log">Log</h3>
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			class="log"
			role="log"
			aria-live="off"
			aria-labelledby="{headingId}-log"
			tabindex="0"
			{@attach follow}
			{onscroll}
		>
			{#if lines.length === 0}
				<p class="none">Nothing has happened yet.</p>
			{:else}
				<ol>
					{#each lines as line, i (i)}
						<li>
							<time>{line.time}</time>
							<span class="stage-name">{line.stage}</span>
							<span class="status">{line.status}</span>
							<span class="src">{line.source}</span>
							<span class="detail">{line.detail}</span>
						</li>
					{/each}
				</ol>
			{/if}
		</div>
	</div>

	{#if actions}<div class="foot">{@render actions()}</div>{/if}
</section>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-width: 0;
		padding: var(--space-6);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.top {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
	}
	h2 {
		font-size: var(--text-xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
		overflow-wrap: anywhere;
	}
	h3 {
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.mark {
		display: inline-flex;
	}
	.mark :global(svg),
	.stage :global(svg),
	.closing :global(svg) {
		width: 0.875rem;
		height: 0.875rem;
		flex: none;
	}
	/* The fill is ink: the one accent block of this view is the primary button. */
	.meter {
		height: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		overflow: hidden;
	}
	.meter > div {
		height: 100%;
		background: var(--color-text);
		transition: width var(--duration-base) var(--ease-out);
	}
	.scroll {
		overflow-x: auto;
	}
	table {
		width: 100%;
		min-width: 40rem;
		border-collapse: collapse;
	}
	thead th {
		padding: 0 var(--space-3) var(--space-2) 0;
		text-align: left;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	td,
	tbody th {
		padding: var(--space-3) var(--space-3) var(--space-3) 0;
		border-top: var(--border-hair) solid var(--color-line);
		vertical-align: top;
		text-align: left;
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
	}
	tbody th {
		font-weight: var(--weight-regular);
	}
	tbody th b {
		display: block;
		font-weight: var(--weight-bold);
	}
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.sub {
		display: block;
		margin-top: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-regular);
	}
	.stage {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		white-space: nowrap;
	}
	.stage.waiting {
		color: var(--color-text-faint);
	}
	.stage.running {
		color: var(--color-warning);
		font-weight: var(--weight-semibold);
	}
	.stage.done {
		color: var(--color-success);
	}
	.stage.skipped {
		color: var(--color-text-muted);
	}
	.stage.failed {
		color: var(--color-danger);
		font-weight: var(--weight-semibold);
	}
	.stage.stopped {
		color: var(--color-text);
		font-weight: var(--weight-semibold);
	}
	.none {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.closing {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		overflow-wrap: anywhere;
	}
	.closing.failed {
		color: var(--color-danger);
	}
	.log-wrap {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.log {
		max-height: 14rem;
		overflow: auto;
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		line-height: 1.7;
	}
	.log ol {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	/* One line per event: a long source key scrolls the log sideways instead of wrapping. */
	.log li {
		display: flex;
		gap: var(--space-3);
		width: max-content;
		min-width: 100%;
		white-space: nowrap;
	}
	.log time {
		flex: none;
		width: 4.5rem;
	}
	.stage-name {
		flex: none;
		width: 5.5rem;
	}
	.log .status {
		flex: none;
		width: 4.5rem;
	}
	.src,
	.detail {
		color: var(--color-text-muted);
	}
	.foot {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding-top: var(--space-5);
		border-top: var(--border-hair) solid var(--color-line);
	}
	@media (prefers-reduced-motion: reduce) {
		.meter > div {
			transition: none;
		}
	}
	@media (max-width: 40rem) {
		.panel {
			padding: var(--space-4);
		}
	}
</style>
