<!--
@component
What the Graph page shows about the selected node: its kind and territory, its fields (the
`get_entity` tool), where its neighbours live, its links by relationship, and its most linked
neighbours, which select in turn. Why: the map shows shape; this panel says what the node holds.
Counts come from the links the map draws, so they match what is lit; `entity` only adds fields.
-->
<script lang="ts">
	import { ExternalLink, X } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { nodeName, type Neighbourhood } from '$lib/graph';
	import {
		LABEL_TYPES,
		NODE_LABELS,
		type Entity,
		type GraphLabel,
		type GraphNode,
		type Territory
	} from '$lib/types';

	type Props = {
		node: GraphNode;
		hood: Neighbourhood;
		territory: Territory | null;
		/** The node's fields; null while they load or when they could not be read. */
		entity?: Entity | null;
		/** Why the fields could not be read. */
		error?: string | null;
		/** Neighbours by uid, to name and rank them. */
		lookup: (uid: string) => GraphNode | undefined;
		onselect?: (uid: string) => void;
		onclose?: () => void;
	};

	let { node, hood, territory, entity = null, error = null, lookup, onselect, onclose }: Props =
		$props();

	const kind = (label: GraphLabel) => NODE_LABELS[LABEL_TYPES[label]];
	const plural = (label: GraphLabel, n: number) => {
		const word = kind(label).toLowerCase();
		return n === 1 ? word : label === 'Person' ? 'people' : `${word}s`;
	};
	const kindWord = $derived(
		node.label === 'WorkItem' && node.kind
			? node.kind === 'pull_request'
				? 'pull request'
				: node.kind.replace(/_/g, ' ')
			: kind(node.label).toLowerCase()
	);
	const stateTone = $derived(
		node.state === 'open' ? 'success' : node.state === 'merged' ? 'accent' : 'neutral'
	);
	const neighbours = $derived(hood.uids.size - 1);
	const top = $derived(
		[...hood.uids]
			.filter((u) => u !== node.uid)
			.map((u) => lookup(u))
			.filter((n): n is GraphNode => !!n)
			.sort((a, b) => b.degree - a.degree || a.uid.localeCompare(b.uid))
			.slice(0, 5)
	);
	const places = $derived(hood.byTerritory.slice(0, 5));
	const rest = $derived(hood.byTerritory.slice(5).reduce((s, t) => s + t.count, 0));
	const widest = $derived(Math.max(1, ...hood.byTerritory.map((t) => t.count)));
	const date = $derived(entity?.date ? formatDate(entity.date) : null);
	const body = $derived(entity?.body?.trim() ? entity.body.trim().slice(0, 280) : null);

	function formatDate(iso: string): string {
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		const sameYear = d.getFullYear() === new Date().getFullYear();
		return d.toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'short',
			...(sameYear ? {} : { year: 'numeric' })
		});
	}
</script>

<aside class="inspector" aria-label="Selected node">
	<header>
		<p class="kind">
			<span class="dot" style:--node="var(--node-{LABEL_TYPES[node.label]})" aria-hidden="true"
			></span>
			<span>{kind(node.label)}{node.is_bot ? ', bot' : ''}</span>
			{#if territory}<span class="where">in {territory.name}</span>{/if}
			{#if node.state}<span class="state"><Badge tone={stateTone}>{node.state}</Badge></span>{/if}
		</p>
		<div class="title">
			<h2>{nodeName(node)}</h2>
			<Button variant="ghost" size="sm" iconOnly label="Close" onclick={onclose}><X /></Button>
		</div>
		<p class="meta">
			{hood.links.toLocaleString('en')}
			{hood.links === 1 ? 'link' : 'links'} to {neighbours.toLocaleString('en')}
			{neighbours === 1 ? 'node' : 'nodes'}{node.comments
				? `, ${node.comments} ${node.comments === 1 ? 'comment' : 'comments'}`
				: ''}
		</p>
	</header>

	<section>
		<h3>Fields</h3>
		<dl>
			{#if node.kind}<dt>kind</dt><dd>{kindWord}</dd>{/if}
			{#if node.number != null}<dt>number</dt><dd class="tabular">{node.number}</dd>{/if}
			{#if date}<dt>date</dt><dd>{date}</dd>{/if}
			{#if body}<dt>body</dt><dd class="body">{body}{entity && entity.body.length > 280 ? '…' : ''}</dd>{/if}
			<dt>uid</dt>
			<dd class="mono">{node.uid}</dd>
		</dl>
		{#if error}
			<p class="note">Fields could not be read: {error}</p>
		{:else if !entity}
			<p class="note">Reading fields…</p>
		{/if}
	</section>

	{#if places.length}
		<section>
			<h3>Where its neighbours live</h3>
			<ul class="bars">
				{#each places as t (t.id)}
					<li>
						<span class="name">{t.name}</span>
						<span class="track" aria-hidden="true"><i style:width="{(t.count / widest) * 100}%"></i></span>
						<span class="tabular count">{t.count.toLocaleString('en')}</span>
					</li>
				{/each}
				{#if rest}
					<li>
						<span class="name muted">{hood.byTerritory.length - 5} more</span>
						<span class="track" aria-hidden="true"><i style:width="{(rest / widest) * 100}%"></i></span>
						<span class="tabular count">{rest.toLocaleString('en')}</span>
					</li>
				{/if}
			</ul>
		</section>
	{/if}

	{#if hood.byRel.length}
		<section>
			<h3>Relationships</h3>
			<ul class="rels">
				{#each hood.byRel as r (`${r.rel}|${r.direction}|${r.label}`)}
					<li>
						<span
							><span class="mono rel">{r.rel}</span>
							{r.direction === 'in' ? 'from ' : ''}{plural(r.label, r.count)}</span
						>
						<span class="tabular count">{r.count.toLocaleString('en')}</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if top.length}
		<section>
			<h3>Most linked neighbours</h3>
			<ul class="near">
				{#each top as n (n.uid)}
					<li>
						<button type="button" onclick={() => onselect?.(n.uid)}>
							<span class="dot" style:--node="var(--node-{LABEL_TYPES[n.label]})" aria-hidden="true"
							></span>
							<span class="sr-only">{kind(n.label)}:</span>
							<span class="name">{nodeName(n)}</span>
							<span class="tabular count">{n.degree.toLocaleString('en')}</span>
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{:else}
		<section>
			<p class="note">No links in this view. Filters may be hiding them.</p>
		</section>
	{/if}

	{#if node.url}
		<footer>
			<Button href={node.url} target="_blank" rel="noreferrer" size="sm"
				>Open on GitHub <ExternalLink aria-hidden="true" /></Button
			>
		</footer>
	{/if}
</aside>

<style>
	.inspector {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow-y: auto;
		background: var(--color-surface);
		border-left: var(--border-hair) solid var(--color-line);
	}
	header,
	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-5);
		border-bottom: var(--border-hair) solid var(--color-line);
	}
	.kind {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.state {
		margin-left: auto;
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
		flex: none;
	}
	.title {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
	}
	h2 {
		flex: 1;
		margin: 0;
		font-size: var(--text-xl);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	.meta,
	.note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	h3 {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	dl {
		display: grid;
		grid-template-columns: 5.5rem minmax(0, 1fr);
		gap: var(--space-1) var(--space-3);
		margin: 0;
		font-size: var(--text-sm);
	}
	dt {
		color: var(--color-text-muted);
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.body {
		white-space: pre-line;
	}
	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.tabular {
		font-variant-numeric: tabular-nums;
	}
	ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--text-sm);
	}
	.bars li {
		display: grid;
		grid-template-columns: 8rem minmax(0, 1fr) 3rem;
		align-items: center;
		gap: var(--space-2);
	}
	.name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.track {
		height: 0.375rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		overflow: hidden;
	}
	.track i {
		display: block;
		height: 100%;
		background: var(--color-text);
	}
	.count {
		text-align: right;
	}
	.rels li {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.rel {
		font-weight: var(--weight-semibold);
	}
	.near button {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		min-height: var(--control-sm);
		padding: 0 var(--space-2);
		margin: 0 calc(-1 * var(--space-2));
		border: 0;
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.near button:hover {
		background: var(--color-surface-sunken);
	}
	.near button:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
	}
	footer {
		display: flex;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-5);
		margin-top: auto;
	}
</style>
