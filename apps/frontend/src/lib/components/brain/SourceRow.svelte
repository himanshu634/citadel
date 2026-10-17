<!--
@component
One source on the Sources page (design direction A, the source ledger): a `<tbody>` with the row
(source and what it reads, status, last sync, read up to, what it put in the graph, actions) and,
when open, its detail (counts per kind with their states, and how it is read). Put it inside the
ledger's `<table>`, after the header row the page draws.

A skipped or blocked source says why under its name and links to Settings, where sources are
edited. Sync on the row downloads only this source; it shows only for sources with a download step
(GitHub, Linear), because loading always walks every source. Counts come from `ledger()` in
`$lib/sources`: two folders of one type share one count, and the row says so.
-->
<script lang="ts">
	import {
		ChevronDown,
		FileJson,
		Folder,
		GitBranch,
		ListChecks,
		RefreshCw,
		TriangleAlert,
		OctagonAlert
	} from '@lucide/svelte';
	import Badge from '../ui/Badge.svelte';
	import Button from '../ui/Button.svelte';
	import {
		creditSummary,
		kindLines,
		sourceTitle,
		statusWord,
		when,
		type Credit
	} from '$lib/sources';
	import { sinceLabel } from '$lib/overview';
	import { GITHUB_PARTS } from '$lib/onboarding';
	import type { SourceRow } from '$lib/types';

	type Props = {
		source: SourceRow;
		credit: Credit;
		/** The company window's start, an ISO date. */
		since: string;
		open?: boolean;
		/** Where the source is edited (the company's Settings). */
		settingsHref: string;
		onsync?: () => void;
		syncing?: boolean;
		/** A build is running: no sync can start. */
		busy?: boolean;
		/** The locations of the sources it shares a count with, by key. */
		locations?: Map<string, string>;
	};

	let {
		source,
		credit,
		since,
		open = $bindable(false),
		settingsHref,
		onsync,
		syncing = false,
		busy = false,
		locations = new Map()
	}: Props = $props();

	const title = $derived(sourceTitle(source.type));
	const status = $derived(statusWord(source.status));
	const lines = $derived(kindLines(credit.groups));
	const most = $derived(Math.max(1, ...lines.map((l) => l.count)));
	const detailId = $derived(`source-${source.key.replace(/[^a-z0-9]+/gi, '-')}`);
	const Icon = $derived(
		source.type === 'github'
			? GitBranch
			: source.type === 'linear'
				? ListChecks
				: source.type === 'local_docs'
					? Folder
					: FileJson
	);
	const reads = $derived(
		source.type === 'github'
			? source.reads.map((r) => GITHUB_PARTS.find((p) => p.part === r)?.label ?? r)
			: source.reads
	);
	const lastRun = $derived(when(source.last_run));
	const cursor = $derived(when(source.cursor));
	const shared = $derived(credit.sharedWith.map((k) => locations.get(k) ?? k));
	const fixable = $derived(source.status === 'skipped' || source.status === 'blocked');
	const fmt = (n: number) => n.toLocaleString('en-GB');
</script>

<tbody class={['source', { open }]}>
	<tr>
		<th scope="row">
			<div class="name">
			<span class="icon"><Icon aria-hidden="true" /></span>
			<span class="who">
				<span class="title">{title}</span>
				<span class="location">{source.location}</span>
				{#if source.problem}
					<span class={['problem', source.status]}>
						{#if source.status === 'blocked'}
							<OctagonAlert aria-hidden="true" />
						{:else}
							<TriangleAlert aria-hidden="true" />
						{/if}
						{source.problem}
					</span>
				{/if}
			</span>
			</div>
		</th>
		<td><Badge tone={status.tone}>{status.word}</Badge></td>
		<td>
			{#if lastRun}
				<span class="main tabular">{lastRun}</span>
				{#if source.records !== null}
					<span class="sub tabular">{fmt(source.records)} records loaded</span>
				{/if}
			{:else}
				<span class="none">Never</span>
			{/if}
		</td>
		<td>
			{#if cursor}
				<span class="main tabular">{cursor}</span>
				<span class="sub">from {sinceLabel(since)}</span>
			{:else}
				<span class="none">Nothing read</span>
			{/if}
		</td>
		<td>
			{#if credit.total > 0}
				<span class="main tabular">{fmt(credit.total)} nodes</span>
				<span class="sub">
					{#if shared.length > 0}Counted with {shared.length === 1 ? '1 other source' : `${shared.length} other sources`}
					{:else}{creditSummary(lines)}{/if}
				</span>
			{:else}
				<span class="none">Nothing yet</span>
			{/if}
		</td>
		<td class="actions">
			{#if fixable}
				<!-- A skipped folder is fixed in Settings; a blocked download is fixed in .env (the problem
				says so), and Settings is where the source can be removed instead. -->
				<Button size="sm" href={settingsHref}>
					{source.status === 'skipped' ? 'Fix in Settings' : 'Open Settings'}
				</Button>
			{:else if source.downloads && onsync}
				<Button size="sm" onclick={onsync} loading={syncing} disabled={busy}>
					<RefreshCw aria-hidden="true" />Sync
				</Button>
			{/if}
			<button
				type="button"
				class="toggle"
				aria-expanded={open}
				aria-controls={detailId}
				aria-label="{open ? 'Hide' : 'Show'} details of {title} {source.location}"
				onclick={() => (open = !open)}
			>
				<ChevronDown aria-hidden="true" />
			</button>
		</td>
	</tr>
	<tr class="detail-row" id={detailId} hidden={!open}>
		<td colspan="6">
			<div class="detail">
				<section aria-label="What {title} put in the graph">
					<h3>What it put in the graph</h3>
					{#if lines.length > 0}
						<ul class="kinds">
							{#each lines as line (line.name)}
								<li>
									<span class="kind-name">
										<span
											class="mark"
											style:background={line.type ? `var(--node-${line.type})` : 'var(--color-line-strong)'}
										></span>
										{line.name}
									</span>
									<span class="count tabular">{fmt(line.count)}</span>
									<span class="track" aria-hidden="true">
										<span
											class="fill"
											style:width="{Math.max(1, (line.count / most) * 100)}%"
											style:background={line.type ? `var(--node-${line.type})` : 'var(--color-line-strong)'}
										></span>
									</span>
									<span class="states">{line.detail}</span>
								</li>
							{/each}
						</ul>
						{#if shared.length > 0}
							<p class="note">
								Counted together with {shared.join(', ')}: sources of one type write the same
								label, so the graph cannot tell their nodes apart.
							</p>
						{/if}
						{#if credit.extraLabels.length > 0}
							<p class="note">
								Includes records that name their own source:
								{#each credit.extraLabels as label, i (label)}{i > 0 ? ', ' : ''}<code>{label}</code>{/each}.
							</p>
						{/if}
					{:else}
						<p class="note">Nothing from this source is in the graph yet.</p>
					{/if}
				</section>
				<section aria-label="How {title} is read">
					<h3>How it is read</h3>
					<dl class="facts">
						{#if reads.length > 0}
							<dt>Reads</dt>
							<dd>{reads.join(', ')}</dd>
						{/if}
						<dt>Window</dt>
						<dd>Activity since {sinceLabel(since)}</dd>
						<dt>Next sync</dt>
						<dd>
							{#if source.problem}
								{source.status === 'blocked' ? 'Fails' : 'Skips this source'} until it is fixed
							{:else if source.window_changed}
								Reloads everything since {sinceLabel(since)}: the window changed
							{:else if cursor}
								Reads what changed after {cursor}
							{:else}
								Reads everything since {sinceLabel(since)}
							{/if}
						</dd>
						<dt>Sync key</dt>
						<dd><code>{source.key}</code></dd>
					</dl>
					{#if source.type === 'github'}
						<div>
							<Button size="sm" href="https://github.com/{source.location}" target="_blank" rel="noreferrer">
								Open on GitHub
							</Button>
						</div>
					{/if}
				</section>
			</div>
		</td>
	</tr>
</tbody>

<style>
	/* Every source starts with a hairline; the first one draws the line under the header row. */
	.source > tr:first-child > * {
		border-top: var(--border-hair) solid var(--color-line);
	}
	.source.open > tr:first-child {
		background: var(--color-surface-sunken);
	}
	th,
	td {
		padding: var(--space-3) var(--space-4);
		text-align: left;
		vertical-align: top;
		font-weight: var(--weight-regular);
	}
	.name {
		display: flex;
		gap: var(--space-3);
		min-width: 0;
	}
	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
	}
	.source.open .icon {
		background: var(--color-surface);
	}
	.icon :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	.who {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.title {
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.location,
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		overflow-wrap: anywhere;
	}
	.problem {
		display: flex;
		gap: var(--space-1);
		align-items: flex-start;
		margin-top: var(--space-1);
		font-size: var(--text-sm);
	}
	.problem :global(svg) {
		flex: none;
		width: 0.875rem;
		height: 0.875rem;
		margin-top: 2px;
	}
	.problem.skipped {
		color: var(--color-warning);
	}
	.problem.blocked {
		color: var(--color-danger);
	}
	.main,
	.sub,
	.none {
		display: block;
	}
	.sub {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.none {
		color: var(--color-text-muted);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: var(--space-2);
		white-space: nowrap;
	}
	.actions :global(.btn svg) {
		width: 0.875rem;
		height: 0.875rem;
	}
	.toggle {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text);
		cursor: pointer;
		transition: background var(--duration-fast) var(--ease-out);
	}
	.toggle:hover {
		background: var(--color-surface-sunken);
	}
	.toggle:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: 2px;
	}
	.toggle :global(svg) {
		width: 1rem;
		height: 1rem;
		transition: transform var(--duration-base) var(--ease-out);
	}
	.source.open .toggle :global(svg) {
		transform: rotate(180deg);
	}
	.detail-row > td {
		padding: 0;
		background: var(--color-ground);
		border-top: var(--border-hair) solid var(--color-line);
	}
	.detail {
		display: grid;
		grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
		gap: var(--space-8);
		padding: var(--space-5) var(--space-4) var(--space-5) calc(var(--space-4) * 2 + var(--control-sm));
	}
	@media (max-width: 900px) {
		.detail {
			grid-template-columns: minmax(0, 1fr);
			gap: var(--space-5);
			padding-left: var(--space-4);
		}
	}
	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}
	h3 {
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		color: var(--color-text-muted);
	}
	.kinds {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.kinds li {
		display: grid;
		grid-template-columns: minmax(9rem, 12rem) 4.5rem minmax(4rem, 1fr) minmax(0, 12rem);
		gap: var(--space-3);
		align-items: center;
		font-size: var(--text-sm);
	}
	.kind-name {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}
	.mark {
		width: 8px;
		height: 8px;
		flex: none;
		border-radius: var(--radius-full);
	}
	.count {
		text-align: right;
		font-weight: var(--weight-bold);
	}
	.track {
		position: relative;
		height: 8px;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		overflow: hidden;
	}
	.fill {
		position: absolute;
		inset: 0 auto 0 0;
		border-radius: var(--radius-sm);
	}
	.states {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	@media (max-width: 720px) {
		.kinds li {
			grid-template-columns: minmax(0, 1fr) auto;
		}
		.track,
		.states {
			grid-column: 1 / -1;
		}
	}
	.note {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
		max-width: 60ch;
	}
	.facts {
		display: grid;
		grid-template-columns: max-content minmax(0, 1fr);
		gap: var(--space-2) var(--space-4);
		margin: 0;
		font-size: var(--text-sm);
	}
	.facts dt {
		color: var(--color-text-muted);
	}
	.facts dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.tabular {
		font-variant-numeric: tabular-nums;
	}
	@media (prefers-reduced-motion: reduce) {
		.toggle,
		.toggle :global(svg) {
			transition: none;
		}
	}
</style>
