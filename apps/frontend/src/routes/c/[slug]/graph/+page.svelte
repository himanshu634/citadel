<!--
@component
The Graph page (design direction D, "Territories"): the whole company graph at once, every node in
the territory of the system it touches most. Find a node, filter kinds and relationships, show or
hide bots, switch to a list. A selection opens the inspector and is kept in the URL (`?focus=`),
so a node can be linked to.

Why this shape: the map answers "what is in this graph and how does it hang together"; the
inspector answers "what does this node hold". Only `ready` and `failed` companies fetch, like the
overview (`viewOf`). The layout runs in a worker (`graphLayout.ts`), because it takes seconds.
-->
<script lang="ts">
	import { CloudOff, List, LoaderCircle, Map as MapIcon, SlidersHorizontal } from '@lucide/svelte';
	import { Popover } from 'bits-ui';
	import { resolve } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { Banner, Button, Checkbox, EmptyState, NodeInspector, RefLink, TerritoryMap } from '$lib';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import { kept, neighbourhood, nodeName, search, tally, type MapLayout } from '$lib/graph';
	import { cachedLayout, computeLayout } from '$lib/graphLayout';
	import { refUrl } from '$lib/links';
	import { buildingTitle, viewOf } from '$lib/overview';
	import {
		LABEL_TYPES,
		NODE_LABELS,
		type Entity,
		type GraphLabel,
		type GraphView,
		type MapDetails
	} from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const status = $derived(company ? viewOf(company) : null);
	const fetchable = $derived(status?.kind === 'data');
	const syncedAt = $derived(company?.last_synced_at ?? null);
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));

	let bots = $state(false);
	let attempt = $state(0);
	/** The last answers, whichever company they were for; only the current slug's are shown. */
	let loaded = $state.raw<GraphView | null>(null);
	let placed = $state.raw<{ view: GraphView; layout: MapLayout } | null>(null);
	let problem = $state<{ slug: string; message: string } | null>(null);

	const graph = $derived(loaded?.slug === data.slug && loaded.bots_shown === bots ? loaded : null);
	const layout = $derived(placed && placed.view === graph ? placed.layout : null);
	const error = $derived(problem?.slug === data.slug ? problem.message : null);

	$effect(() => {
		const slug = data.slug;
		const withBots = bots;
		void attempt;
		void syncedAt; // a finished sync or build redraws the map
		if (!fetchable) return;
		problem = null;
		let live = true;
		api.graph(slug, withBots).then(
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

	// Filters: hide in place, so the map stays where it is. Bots are a refetch (they add nodes).
	const counts = $derived(graph ? tally(graph) : { kinds: [], rels: [] });
	let hiddenKinds = $state<GraphLabel[]>([]);
	let hiddenRels = $state<string[]>([]);
	const keep = $derived.by(() => {
		if (!graph || (!hiddenKinds.length && !hiddenRels.length)) return null;
		const kinds = new Set(counts.kinds.map(([k]) => k).filter((k) => !hiddenKinds.includes(k)));
		const rels = new Set(counts.rels.map(([r]) => r).filter((r) => !hiddenRels.includes(r)));
		return kept(graph, kinds, rels);
	});
	const filtered = $derived(hiddenKinds.length + hiddenRels.length);
	function toggle<T>(list: T[], value: T, on: boolean): T[] {
		return on ? list.filter((v) => v !== value) : [...list, value];
	}

	// Selection: read from the URL when the page opens, written back to it on every change. A
	// shallow replaceState does not update `page.url`, so the selection itself is local state.
	let focus = $state<string | null>(page.url.searchParams.get('focus'));
	const selected = $derived(focus && graph?.nodes.some((n) => n.uid === focus) ? focus : null);
	function select(uid: string | null) {
		focus = uid;
		const query = uid ? `?${new URLSearchParams({ focus: uid })}` : '';
		replaceState(`${resolve('/c/[slug]/graph', { slug: data.slug })}${query}`, {});
	}
	const byUid = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n])));
	const node = $derived(selected ? (byUid.get(selected) ?? null) : null);
	const hood = $derived(
		graph && selected
			? neighbourhood(
					keep ? { ...graph, edges: graph.edges.filter((_, i) => keep.edges[i]) } : graph,
					selected
				)
			: null
	);
	const territory = $derived(node ? (graph?.territories.find((t) => t.id === node.territory) ?? null) : null);

	/** What the map's hover card reads, with the API's errors said in words. */
	const details: MapDetails = {
		node: (uid) => api.graphNode(data.slug, uid).catch(fail),
		link: (a, b) => api.graphLink(data.slug, a, b).catch(fail)
	};
	function fail(e: unknown): never {
		throw new Error(describeError(e));
	}

	let entity = $state.raw<{ uid: string; value: Entity | null; error: string | null } | null>(null);
	$effect(() => {
		const uid = selected;
		const slug = data.slug;
		if (!uid) return;
		let live = true;
		api.entity(slug, uid).then(
			(value) => {
				if (live) entity = { uid, value, error: value ? null : 'This node is no longer in the graph.' };
			},
			(e) => {
				if (live) entity = { uid, value: null, error: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});
	const fields = $derived(entity?.uid === selected ? entity : null);

	// Find: a combobox over the loaded nodes.
	let query = $state('');
	let active = $state(0);
	let finding = $state(false);
	const results = $derived(graph && query.trim() ? search(graph, query) : []);
	function pick(uid: string) {
		select(uid);
		query = '';
		finding = false;
	}
	function onfindkey(e: KeyboardEvent) {
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			finding = true;
			active = Math.min(active + 1, results.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			active = Math.max(active - 1, 0);
		} else if (e.key === 'Enter' && results[active]) {
			e.preventDefault();
			pick(results[active].uid);
		} else if (e.key === 'Escape') {
			query = '';
			finding = false;
		}
	}

	let filtersOpen = $state(false);

	/** Escape clears the selection, unless it was meant for a field or the filters panel. */
	function onescape(e: KeyboardEvent) {
		if (e.key !== 'Escape' || !selected || e.defaultPrevented || filtersOpen) return;
		const target = e.target instanceof Element ? e.target : null;
		if (target?.closest('input, textarea, select, .graph-filters, [role="dialog"]')) return;
		select(null);
	}
	let listing = $state(false);
	let shownRows = $state(200);
	const rows = $derived(
		(graph?.nodes ?? [])
			.filter((n) => !keep || keep.nodes.has(n.uid))
			.toSorted((a, b) => b.degree - a.degree || a.uid.localeCompare(b.uid))
	);
	const territoryName = $derived(new Map((graph?.territories ?? []).map((t) => [t.id, t.name])));

	const kind = (label: GraphLabel) => NODE_LABELS[LABEL_TYPES[label]];
	const n = (v: number) => v.toLocaleString('en');
	const summary = $derived(
		graph
			? `${n(graph.territories.length)} territories, ${n(keep?.nodes.size ?? graph.nodes.length)} nodes, ${n(keep ? keep.edges.filter(Boolean).length : graph.edges.length)} relationships`
			: ''
	);
</script>

<svelte:head><title>Graph · {company?.name ?? 'Graph'} | Citadel</title></svelte:head>
<svelte:window onkeydowncapture={onescape} />

{#if company && status}
	<div class="graph-page">
		<header class="bar">
			<h1>Graph</h1>
			{#if graph}
				<div class="find">
					<input
						type="search"
						role="combobox"
						aria-label="Find a node"
						aria-expanded={finding && results.length > 0}
						aria-controls="graph-find-results"
						aria-autocomplete="list"
						aria-activedescendant={finding && results[active] ? `find-${active}` : undefined}
						placeholder="Find a person, system or PR"
						bind:value={query}
						oninput={() => {
							finding = true;
							active = 0;
						}}
						onkeydown={onfindkey}
						onblur={() => setTimeout(() => (finding = false), 120)}
					/>
					{#if finding && results.length}
						<ul id="graph-find-results" role="listbox" aria-label="Matching nodes">
							{#each results as r, i (r.uid)}
								<li
									id="find-{i}"
									role="option"
									aria-selected={i === active}
									class={{ active: i === active }}
									onpointerdown={(e) => {
										e.preventDefault();
										pick(r.uid);
									}}
								>
									<span class="dot" style:--node="var(--node-{LABEL_TYPES[r.label]})" aria-hidden="true"></span>
									<span class="name">{nodeName(r)}</span>
									<span class="meta">{kind(r.label)}, {territoryName.get(r.territory)}</span>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
				<p class="summary">{summary}</p>
				<div class="actions">
					<Popover.Root bind:open={filtersOpen}>
						<Popover.Trigger>
							{#snippet child({ props })}
								<Button {...props} size="sm"
									><SlidersHorizontal aria-hidden="true" />{filtered ? `Filters: ${filtered} hidden` : 'Filters'}</Button
								>
							{/snippet}
						</Popover.Trigger>
						<Popover.Portal>
							<Popover.Content class="graph-filters" sideOffset={6} align="end">
								<fieldset>
									<legend>Kinds</legend>
									{#each counts.kinds as [k, c] (k)}
										<Checkbox
											label="{kind(k)} ({n(c)})"
											bind:checked={
												() => !hiddenKinds.includes(k), (on) => (hiddenKinds = toggle(hiddenKinds, k, on))
											}
										/>
									{/each}
								</fieldset>
								<fieldset>
									<legend>Relationships</legend>
									{#each counts.rels as [r, c] (r)}
										<Checkbox
											label="{r} ({n(c)})"
											bind:checked={
												() => !hiddenRels.includes(r), (on) => (hiddenRels = toggle(hiddenRels, r, on))
											}
										/>
									{/each}
								</fieldset>
								<fieldset>
									<legend>Hidden by default</legend>
									<Checkbox label="Bots ({n(graph.bots)})" bind:checked={bots} disabled={!graph.bots} />
									<p class="note">
										{n(graph.comments)} comments are counted on their work items, not drawn.
									</p>
								</fieldset>
							</Popover.Content>
						</Popover.Portal>
					</Popover.Root>
					<Button size="sm" aria-pressed={listing} onclick={() => (listing = !listing)}>
						{#if listing}<MapIcon aria-hidden="true" />Map{:else}<List aria-hidden="true" />List{/if}
					</Button>
				</div>
			{/if}
		</header>

		{#if status.kind === 'invalid'}
			<div class="pad"><Banner tone="danger" title="Config invalid">{status.error}</Banner></div>
		{:else if status.kind === 'unreachable'}
			<div class="pad">
				<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
					Citadel can't reach FalkorDB, so the graph can't be drawn. Start it with <code>make up</code>.
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
					description="Every person, system and piece of work in {company.name}'s activity is drawn here once it is in the graph."
				/>
			</div>
		{:else if error}
			<div class="pad">
				<EmptyState title="Can't read {company.name}'s graph" description={error}>
					{#snippet action()}<Button onclick={() => attempt++}>Try again</Button>{/snippet}
				</EmptyState>
			</div>
		{:else if graph && !graph.nodes.length}
			<div class="pad">
				<EmptyState
					title="Nothing in this graph yet"
					description="No people, systems or work are loaded. Run a build to read {company.name}'s sources."
				>
					{#snippet action()}<Button href={buildPath}>See build</Button>{/snippet}
				</EmptyState>
			</div>
		{:else if !graph || !layout}
			<div class="drawing" role="status" aria-busy="true">
				<LoaderCircle class="spin" aria-hidden="true" />
				{graph ? `Drawing ${n(graph.nodes.length)} nodes` : 'Reading the graph'}
			</div>
		{:else}
			{#if status.building}
				<div class="pad">
					<Banner tone="warning" title={buildingTitle(company)} icon={LoaderCircle} spin>
						{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
					</Banner>
				</div>
			{:else if status.failure}
				<div class="pad">
					<Banner tone="danger" title="Last build failed">
						{status.failure}
						{#snippet action()}<Button href={buildPath}>See details</Button>{/snippet}
					</Banner>
				</div>
			{/if}
			<div class={['body', { inspecting: node && hood }]}>
				<div class="view">
					{#if listing}
						<div class="list">
							<table>
								<caption class="sr-only">Nodes in the graph, most linked first</caption>
								<thead>
									<tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Territory</th><th scope="col" class="num">Links</th></tr>
								</thead>
								<tbody>
									{#each rows.slice(0, shownRows) as r (r.uid)}
										{@const href = refUrl(r.uid, r.url)}
										<tr class={{ current: r.uid === selected }}>
											<td>
												<span class="name-cell">
													<button type="button" aria-current={r.uid === selected ? 'true' : undefined} onclick={() => select(r.uid)}>
														<span class="dot" style:--node="var(--node-{LABEL_TYPES[r.label]})" aria-hidden="true"></span>
														{nodeName(r)}
													</button>
													{#if href}<RefLink icon {href} label={nodeName(r)} />{/if}
												</span>
											</td>
											<td>{kind(r.label)}{r.is_bot ? ', bot' : ''}</td>
											<td>{territoryName.get(r.territory)}</td>
											<td class="num">{n(r.degree)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
							{#if rows.length > shownRows}
								<div class="more">
									<Button size="sm" onclick={() => (shownRows += 500)}
										>Show more ({n(rows.length - shownRows)} left)</Button
									>
								</div>
							{/if}
						</div>
					{:else}
						<TerritoryMap
							view={graph}
							{layout}
							{selected}
							{keep}
							onselect={select}
							{details}
						/>
					{/if}
				</div>
				{#if node && hood}
					<div class="side">
						<NodeInspector
							{node}
							{hood}
							{territory}
							entity={fields?.value ?? null}
							error={fields?.error ?? null}
							lookup={(uid) => byUid.get(uid)}
							onselect={select}
							onclose={() => select(null)}
						/>
					</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.graph-page {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3) var(--space-4);
		padding: var(--space-3) var(--space-5);
		background: var(--color-surface);
		border-bottom: var(--border-hair) solid var(--color-line);
	}
	h1 {
		margin: 0;
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
	}
	.find {
		position: relative;
		width: min(20rem, 100%);
	}
	.find input {
		width: 100%;
		height: var(--control-sm);
		padding: 0 var(--space-3);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.find input:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: 1px;
	}
	.find ul {
		position: absolute;
		z-index: 20;
		top: calc(100% + var(--space-1));
		left: 0;
		width: min(28rem, 90vw);
		margin: 0;
		padding: var(--space-1);
		list-style: none;
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	.find li {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		align-items: center;
		column-gap: var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.find li.active {
		background: var(--color-accent-soft);
	}
	.find .name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.find .meta {
		grid-column: 2;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
		flex: none;
		display: inline-block;
	}
	.summary {
		flex: 1 1 12rem;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		margin-left: auto;
		flex: none;
	}
	:global(.graph-filters) {
		z-index: 30;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: 17rem;
		max-height: min(32rem, 80dvh);
		overflow-y: auto;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	:global(.graph-filters) fieldset {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		border: 0;
	}
	:global(.graph-filters) legend {
		margin-bottom: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
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
		background: var(--color-surface);
	}
	.drawing :global(.spin) {
		width: 1rem;
		height: 1rem;
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(1turn);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.drawing :global(.spin) {
			animation: none;
		}
	}
	.body {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.body.inspecting {
		grid-template-columns: minmax(0, 1fr) 20rem;
	}
	.view,
	.side {
		min-height: 0;
		overflow: hidden;
	}
	.list {
		height: 100%;
		overflow: auto;
		background: var(--color-surface);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	th {
		position: sticky;
		top: 0;
		padding: var(--space-2) var(--space-4);
		background: var(--color-surface);
		border-bottom: var(--border-hair) solid var(--color-line);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		text-align: left;
	}
	td {
		padding: var(--space-1) var(--space-4);
		border-bottom: var(--border-hair) solid var(--color-line);
		vertical-align: middle;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.name-cell {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}
	td button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		max-width: 36rem;
		min-height: var(--control-sm);
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	td button:hover {
		text-decoration: underline;
	}
	td button:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: 2px;
	}
	tr.current td {
		background: var(--color-accent-soft);
	}
	.more {
		padding: var(--space-4);
	}
	@media (max-width: 900px) {
		.body.inspecting {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: minmax(0, 1fr) minmax(0, 45%);
		}
		.side :global(.inspector) {
			border-left: 0;
			border-top: var(--border-hair) solid var(--color-line);
		}
	}
</style>
