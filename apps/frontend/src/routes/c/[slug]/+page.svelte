<!--
@component
One company's overview: the counts and lists from `GET /api/companies/<slug>/overview`, and a
banner or empty state for every status the company can be in. Why: the status decides what exists
to show. A building company has no graph yet, an invalid one has no config to read, an unreachable
one cannot be asked, so only `ready` and `failed` fetch. The fetch is guarded (`companies.guard`)
so a slow answer for the company you just left is never drawn under the one you are on.
-->
<script lang="ts">
	import { CloudOff, LoaderCircle, Network, RefreshCw } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import {
		ActivityBars,
		Banner,
		Button,
		Card,
		EmptyState,
		EntityRow,
		Stat,
		Tabs,
		Tooltip,
		WorkItemRow
	} from '$lib';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import {
		buildingTitle,
		peopleRows,
		sinceLabel,
		statCards,
		systemBars,
		viewOf,
		workItemOf
	} from '$lib/overview';
	import { startSync, type SyncOutcome } from '$lib/sync';
	import type { Overview } from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const view = $derived(company ? viewOf(company) : null);
	// Primitives, so a status event that changes nothing here does not refetch.
	const fetchable = $derived(view?.kind === 'data');
	const syncedAt = $derived(company?.last_synced_at ?? null);
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));
	const graphPath = $derived(resolve(`/c/${data.slug}/graph` as `/c/${string}`));

	/** The last answer, whichever company it was for; only the current slug's is ever shown. */
	let loaded = $state<Overview | null>(null);
	let problem = $state<{ slug: string; message: string } | null>(null);
	let attempt = $state(0);

	const overview = $derived(loaded?.slug === data.slug ? loaded : null);
	const error = $derived(problem?.slug === data.slug ? problem.message : null);
	const loading = $derived(fetchable && !overview && !error);

	$effect(() => {
		const slug = data.slug;
		void attempt;
		void syncedAt; // a finished sync or build refreshes the numbers
		if (!fetchable) return;
		problem = null; // a new fetch starts: show the skeleton, not an old error
		let live = true;
		api.overview(slug).then(
			(answer) => {
				const mine = companies.guard(slug, answer);
				if (!live || !mine) return;
				loaded = mine;
				problem = null;
			},
			(e) => {
				if (live && slug === companies.current) problem = { slug, message: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});

	function retry() {
		problem = null;
		attempt++;
	}

	// Sync now. `syncing` and `syncFailed` name the slug they belong to, like `problem` above.
	let syncing = $state<string | null>(null);
	let syncFailed = $state<{ slug: string; outcome: Exclude<SyncOutcome, { kind: 'started' }> } | null>(
		null
	);
	const syncProblem = $derived(syncFailed?.slug === data.slug ? syncFailed.outcome : null);

	async function syncNow() {
		const slug = data.slug;
		if (syncing === slug) return; // set before the first await, so a double click sends one request
		syncing = slug;
		syncFailed = null;
		const outcome = await startSync(slug);
		if (outcome.kind !== 'started') syncFailed = { slug, outcome };
		await companies.load(); // the status flips to building, which swaps the buttons for the banner
		if (syncing === slug) syncing = null;
	}

	// Tooltip props carry their own click handler; keep it and add ours.
	function onsync(props: Record<string, unknown>) {
		return (e: MouseEvent) => {
			(props.onclick as ((e: MouseEvent) => void) | undefined)?.(e);
			void syncNow();
		};
	}

	const cards = $derived(overview ? statCards(overview.counts) : []);
	const work = $derived((overview?.recent ?? []).map(workItemOf));
	const empty = $derived(overview !== null && cards.length === 0 && work.length === 0);
	const since = $derived(overview ? sinceLabel(overview.since) : null);

	let workFilter = $state('all');
	const openCount = $derived(work.filter((w) => w.state === 'open').length);
	const tabItems = $derived([
		{ value: 'all', label: 'All', count: work.length },
		{ value: 'open', label: 'Open', count: openCount },
		{ value: 'closed', label: 'Closed', count: work.length - openCount }
	]);
</script>

<svelte:head><title>{company?.name ?? 'Overview'} | Citadel</title></svelte:head>

{#if company && view}
	<div class="page">
		<header class="page-head">
			<div>
				<h1>{company.name}</h1>
				<p>
					{#if since}Engineering activity since {since}, in graph{:else}Graph{/if}
					<code>brain_{company.slug}</code>.
				</p>
			</div>
			{#if view.kind === 'data' && !view.building}
				<div class="head-actions">
					<Tooltip text="Pull new activity from every source">
						{#snippet trigger(props)}
							<Button {...props} onclick={onsync(props)} loading={syncing === data.slug}>
								<RefreshCw aria-hidden="true" />Sync now
							</Button>
						{/snippet}
					</Tooltip>
					<Button variant="primary" href={graphPath}><Network aria-hidden="true" />Open graph</Button>
				</div>
			{/if}
		</header>

		{#if view.kind === 'invalid'}
			<Banner tone="danger" title="Config invalid">{view.error}</Banner>
		{:else if view.kind === 'unreachable'}
			<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
				Citadel can't reach FalkorDB, so counts and answers are unavailable. Start it with
				<code>make up</code>.
			</Banner>
		{:else if view.kind === 'waiting'}
			<Banner
				tone="warning"
				title={buildingTitle(company)}
				icon={company.status === 'building' ? LoaderCircle : undefined}
				spin={company.status === 'building'}
			>
				{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
			</Banner>
			<EmptyState
				title="Answers appear when the first build finishes"
				description="Counts, recent work and people show up here once Citadel has loaded {company.name}'s activity into the graph."
			/>
		{:else}
			{#if syncProblem?.kind === 'running' && !view.building}
				<Banner tone="warning" title="A build is running">
					Wait for it to finish, or stop it from its progress page, then sync again.
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
			{:else if syncProblem?.kind === 'failed'}
				<Banner tone="danger" title="Could not start the sync">{syncProblem.message}</Banner>
			{/if}
			{#if view.building}
				<Banner tone="warning" title={buildingTitle(company)} icon={LoaderCircle} spin>
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
			{/if}
			{#if view.failure}
				<Banner tone="danger" title="Last build failed">
					{view.failure}
					{#snippet action()}<Button href={buildPath}>See details</Button>{/snippet}
				</Banner>
			{/if}

			{#if error}
				<EmptyState title="Can't read {company.name}'s graph" description={error}>
					{#snippet action()}<Button onclick={retry}>Try again</Button>{/snippet}
				</EmptyState>
			{:else if loading}
				<div class="skeleton" role="status" aria-busy="true">
					<span class="sr-only">Loading overview</span>
					<div class="block summary-skeleton"></div>
					<div class="skeleton-grid">
						<div class="block tall"></div>
						<div class="block tall"></div>
					</div>
				</div>
			{:else if empty}
				<EmptyState
					title="Nothing in this graph yet"
					description="No work items or changes are loaded. Run a build to read {company.name}'s sources."
				>
					{#snippet action()}<Button href={buildPath}>See build</Button>{/snippet}
				</EmptyState>
			{:else if overview}
				<section aria-labelledby="graph-heading" class="summary">
					<h2 id="graph-heading" class="sr-only">Graph contents</h2>
					<dl class="stats">
						{#each cards as c (c.type)}
							<Stat type={c.type} label={c.label} value={c.value} />
						{/each}
					</dl>
				</section>

				<div class="grid">
					<Card title="Recent work" description="Pull requests, issues and threads" class="work-card">
						{#if work.length === 0}
							<p class="muted">No work items in this window.</p>
						{:else}
							<Tabs items={tabItems} bind:value={workFilter} label="Filter work items">
								{#snippet panel(filter)}
									{@const list =
										filter === 'all'
											? work
											: work.filter((w) => (filter === 'open') === (w.state === 'open'))}
									<ul class="list">
										{#each list as item (item.uid)}
											<li><WorkItemRow {item} /></li>
										{/each}
									</ul>
								{/snippet}
							</Tabs>
						{/if}
					</Card>

					<div class="side-col">
						<Card title="Changes by system" description="Commits touching each system since {since}">
							{#if overview.systems.length === 0}
								<p class="muted">No systems yet.</p>
							{:else}
								<ActivityBars unit="changes" items={systemBars(overview.systems)} />
							{/if}
						</Card>

						<Card title="People" description="Authors and reviewers in this graph">
							{#if overview.people.length === 0}
								<p class="muted">No people yet.</p>
							{:else}
								<ul class="list people">
									{#each peopleRows(overview.people) as p (p.key)}
										<li><EntityRow name={p.name} type="person" meta={p.meta} /></li>
									{/each}
								</ul>
							{/if}
						</Card>
					</div>
				</div>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.page-head {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: var(--space-4);
	}
	h1 {
		font-size: var(--text-2xl);
		font-variation-settings: 'wdth' var(--width-brand);
		font-weight: var(--weight-black);
		overflow-wrap: anywhere;
	}
	.page-head p {
		margin-top: var(--space-1);
		color: var(--color-text-muted);
	}
	.head-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.summary {
		padding: var(--space-5);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
		gap: var(--space-5);
		margin: 0;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(12, minmax(0, 1fr));
		gap: var(--space-4);
		align-items: start;
	}
	.grid > :global(.work-card) {
		grid-column: span 8;
	}
	.side-col {
		grid-column: span 4;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}
	@media (max-width: 1100px) {
		.grid > :global(.work-card),
		.side-col {
			grid-column: 1 / -1;
		}
	}
	.list {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.list > li + li {
		border-top: var(--border-hair) solid var(--color-line);
	}
	.people > li + li {
		border-top: 0;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.block {
		background: var(--color-surface-sunken);
		border-radius: var(--radius-md);
	}
	.summary-skeleton {
		height: 6rem;
	}
	.skeleton-grid {
		display: grid;
		grid-template-columns: 2fr 1fr;
		gap: var(--space-4);
	}
	.tall {
		height: 16rem;
	}
	@media (max-width: 720px) {
		.skeleton-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
