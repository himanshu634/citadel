<!--
@component
The Systems page (design direction A, "the map with the agent's trail"): the company map from the
Graph page, with the agents' latest run drawn over it. Each step sits on the node it was about,
numbered in order and joined by an ink line; while the run is going, the node the agent is on
has an ink ring and says what it is doing. The rail lists the run's steps and the earlier runs.

Why this shape: it answers "where is the agent working, and what has it done on the graph" in
one look, on the map people already know. Runs come from GET .../activity (Ask turns today;
Keeper reviews later), read again every few seconds while one is going and less often when not.
The map is laid out once per graph; only the trail moves.
-->
<script lang="ts">
	import { CloudOff, LoaderCircle } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { AgentRun, Banner, Button, EmptyState, TerritoryMap } from '$lib';
	import { actorName, doingNow, featured, shownRun, trailOf, type Pick } from '$lib/activity';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import type { MapLayout } from '$lib/graph';
	import { cachedLayout, computeLayout } from '$lib/graphLayout';
	import { buildingTitle, viewOf } from '$lib/overview';
	import { ago } from '$lib/time';
	import type { Activity, GraphView } from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const status = $derived(company ? viewOf(company) : null);
	const fetchable = $derived(status?.kind === 'data');
	const syncedAt = $derived(company?.last_synced_at ?? null);
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));
	const askPath = $derived(resolve('/c/[slug]/ask', { slug: data.slug }));

	// The map: the Graph page's view and layout (shared cache), fetched once per build.
	let attempt = $state(0);
	let loaded = $state.raw<GraphView | null>(null);
	let placed = $state.raw<{ view: GraphView; layout: MapLayout } | null>(null);
	let problem = $state<{ slug: string; message: string } | null>(null);
	const graph = $derived(loaded?.slug === data.slug ? loaded : null);
	const layout = $derived(placed && placed.view === graph ? placed.layout : null);
	const error = $derived(problem?.slug === data.slug ? problem.message : null);

	$effect(() => {
		const slug = data.slug;
		void attempt;
		void syncedAt;
		if (!fetchable) return;
		problem = null;
		let live = true;
		api.graph(slug).then(
			(answer) => {
				const mine = companies.guard(slug, answer);
				if (!live || !mine) return;
				loaded = mine;
				const hit = cachedLayout(mine);
				if (hit) placed = { view: mine, layout: hit };
				else
					void computeLayout(mine).then((l) => {
						if (live) placed = { view: mine, layout: l };
					});
			},
			(e) => {
				if (live && slug === companies.current) problem = { slug, message: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});

	// The runs: read often while one is going, rarely while idle or in a hidden tab.
	const LIVE_MS = 1500;
	const IDLE_MS = 6000;
	const HIDDEN_MS = 20000;
	let activity = $state.raw<{ slug: string; value: Activity } | null>(null);
	let activityError = $state<string | null>(null);
	const runs = $derived(activity?.slug === data.slug ? activity.value.runs : null);

	$effect(() => {
		const slug = data.slug;
		if (!fetchable) return;
		let live = true;
		let timer: ReturnType<typeof setTimeout> | undefined;
		async function tick() {
			let running = false;
			try {
				const value = await api.activity(slug);
				if (!live) return;
				activity = { slug, value };
				activityError = null;
				running = value.running;
			} catch (e) {
				if (!live) return;
				activityError = describeError(e);
			}
			timer = setTimeout(tick, document.hidden ? HIDDEN_MS : running ? LIVE_MS : IDLE_MS);
		}
		void tick();
		return () => {
			live = false;
			clearTimeout(timer);
		};
	});

	// The run on the map: the one picked in the rail, else one that is going, else the newest.
	// A pick holds while the run it was picked over is still the featured one (see `shownRun`).
	const working = $derived(runs?.find((r) => r.status === 'running') ?? null);
	let picked = $state<Pick | null>(null);
	const run = $derived(runs ? shownRun(runs, picked) : null);
	function pick(id: string) {
		picked = { id, featuredAt: featured(runs ?? [])?.id ?? null };
	}
	const territoryOf = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n.territory])));
	const urls = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n.url])));
	const trail = $derived(run && graph ? trailOf(run, (uid) => territoryOf.get(uid) ?? null) : null);
	const here = $derived(run?.status === 'running' ? `${actorName(run.actor)} · ${doingNow(run)}` : null);
	const others = $derived((runs ?? []).filter((r) => r.id !== run?.id));
	const chatHref = (threadId: string | null) =>
		threadId ? `${askPath}?${new URLSearchParams({ thread: threadId })}` : null;

	const statusLine = $derived(
		working
			? `${actorName(working.actor)} is working now`
			: runs?.length
				? `No agent is working now. The last run started ${ago(runs[0].started_at)}.`
				: runs
					? 'No agent has worked on this graph yet.'
					: ''
	);
</script>

<svelte:head><title>Systems · {company?.name ?? 'Systems'} | Citadel</title></svelte:head>

{#if company && status}
	<div class="systems-page">
		<header class="bar">
			<div class="title">
				<h1>Systems</h1>
				<p class="lede">Where the agents are working, and every step they took on the graph.</p>
			</div>
			{#if statusLine}
				<p class={['state', { live: working }]} role="status">
					{#if working}<span class="ring" aria-hidden="true"></span>{/if}{statusLine}
				</p>
			{/if}
		</header>

		{#if status.kind === 'invalid'}
			<div class="pad"><Banner tone="danger" title="Config invalid">{status.error}</Banner></div>
		{:else if status.kind === 'unreachable'}
			<div class="pad">
				<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
					Citadel can't reach FalkorDB, so the map can't be drawn. Start it with <code>make up</code>.
				</Banner>
			</div>
		{:else if status.kind === 'waiting'}
			<div class="pad">
				<Banner
					tone="warning"
					title={buildingTitle(company)}
					icon={company.status === 'building' ? LoaderCircle : undefined}
					spin={company.status === 'building'}
				>
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
				<EmptyState
					title="The map appears when the first build finishes"
					description="Once {company.name}'s graph is built, every step an agent takes on it is drawn here."
				/>
			</div>
		{:else if error}
			<div class="pad">
				<EmptyState title="Can't read {company.name}'s graph" description={error}>
					{#snippet action()}<Button onclick={() => attempt++}>Try again</Button>{/snippet}
				</EmptyState>
			</div>
		{:else if !graph || !layout}
			<div class="drawing" role="status" aria-busy="true">
				<LoaderCircle class="spin" aria-hidden="true" />
				{graph ? 'Drawing the map' : 'Reading the graph'}
			</div>
		{:else}
			<div class="body">
				<div class="view">
					<TerritoryMap view={graph} {layout} {trail} {here} />
				</div>
				<aside class="side" aria-label="Agent runs">
					{#if activityError && !runs}
						<p class="note">Can't read the agents' runs: {activityError}</p>
					{:else if !runs}
						<p class="note">Reading the agents' runs</p>
					{:else if run && trail}
						<AgentRun {run} {trail} href={chatHref(run.thread_id)} urlOf={(uid) => urls.get(uid) ?? null} />
						{#if others.length}
							<div class="earlier">
								<h2>Other runs</h2>
								<ul>
									{#each others as r (r.id)}
										<li>
											<button type="button" onclick={() => pick(r.id)}>
												<span class="q">{r.title}</span>
												<span class="when">
													{r.status === 'running' ? 'Working now' : ago(r.started_at)} · {r.steps.length}
													{r.steps.length === 1 ? 'step' : 'steps'}
												</span>
											</button>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{:else}
						<EmptyState
							title="No agent has walked this graph yet"
							description="Ask {company.name} a question: each step the agent takes shows here, on the map."
						>
							{#snippet action()}<Button href={askPath}>Ask a question</Button>{/snippet}
						</EmptyState>
					{/if}
				</aside>
			</div>
		{/if}
	</div>
{/if}

<style>
	.systems-page {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3) var(--space-4);
		padding: var(--space-3) var(--space-5);
		background: var(--color-surface);
		border-bottom: var(--border-hair) solid var(--color-line);
	}
	.title {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	h1 {
		margin: 0;
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: var(--leading-tight);
	}
	.lede {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.state {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.state.live {
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-full);
		background: var(--color-text);
		color: var(--color-surface);
		font-weight: var(--weight-semibold);
	}
	.ring {
		width: var(--space-2);
		height: var(--space-2);
		border: var(--border-focus) solid var(--color-surface);
		border-radius: var(--radius-full);
	}
	.pad {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.drawing {
		display: flex;
		flex: 1;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
	}
	.drawing :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.drawing :global(.spin) {
			animation: none;
		}
	}
	.body {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 22rem;
		grid-template-rows: minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.view {
		min-height: 0;
		overflow: hidden;
	}
	.side {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-height: 0;
		overflow: auto;
		padding: var(--space-5);
		background: var(--color-surface);
		border-left: var(--border-hair) solid var(--color-line);
	}
	.note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.earlier h2 {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.earlier ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.earlier button {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		width: 100%;
		padding: var(--space-2) 0;
		border: 0;
		border-top: var(--border-hair) solid var(--color-line);
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.earlier button:hover .q {
		text-decoration: underline;
	}
	.earlier button:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: var(--border-focus);
	}
	.q {
		font-size: var(--text-md);
	}
	.when {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	@media (max-width: 64rem) {
		.body {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: minmax(0, 1fr) minmax(0, 45%);
		}
		.side {
			border-left: 0;
			border-top: var(--border-hair) solid var(--color-line);
		}
	}
</style>
