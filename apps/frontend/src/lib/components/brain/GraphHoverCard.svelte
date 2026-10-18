<!--
@component
What one node or link of the graph map stores, shown while the pointer is on it (the Graph page).
Why: the map shows shape and the inspector shows a selection; this card answers "what is in
here" without a click. A node lists every property it was loaded with; a link lists each
relationship between the two nodes with what it stores. The map places the card; it never takes
the pointer (it is read, not used), so long values are cut and the card does not scroll.
-->
<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';
	import type { PropRow } from '$lib/graph';
	import { LABEL_TYPES, type GraphLabel } from '$lib/types';

	type End = { name: string; label: GraphLabel };
	type Section = { heading?: string; rows: PropRow[] };

	type Props = {
		/** A node: its name and kind. */
		node?: (End & { kind: string }) | null;
		/** A link: its two ends (the first is where the arrow starts). */
		link?: { from: End; to: End } | null;
		/** One block per relationship (a link) or one block (a node). */
		sections?: Section[];
		/** The node's properties are still being read. */
		loading?: boolean;
		/** Why they could not be read. */
		error?: string | null;
	};

	let { node = null, link = null, sections = [], loading = false, error = null }: Props = $props();

	const dot = (label: GraphLabel) => `var(--node-${LABEL_TYPES[label]})`;
</script>

<div class="card" role="tooltip">
	{#if node}
		<p class="kicker">
			<span class="dot" style:--node={dot(node.label)} aria-hidden="true"></span>{node.kind}
		</p>
		<p class="title">{node.name}</p>
	{:else if link}
		<p class="kicker">{sections.length === 1 ? 'Link' : `${sections.length} links`}</p>
		<p class="ends">
			<span class="end"><span class="dot" style:--node={dot(link.from.label)} aria-hidden="true"></span>{link.from.name}</span>
			<span class="end"><span class="dot" style:--node={dot(link.to.label)} aria-hidden="true"></span>{link.to.name}</span>
		</p>
	{/if}

	{#if loading}
		<p class="status"><LoaderCircle class="spin" aria-hidden="true" />Reading what it stores…</p>
	{:else if error}
		<p class="status error">{error}</p>
	{:else}
		{#each sections as section, i (i)}
			<div class="section">
				{#if section.heading}<p class="rel">{section.heading}</p>{/if}
				{#if section.rows.length}
					<dl>
						{#each section.rows as row (row.key)}
							<dt>{row.key}</dt>
							<dd>{row.value}</dd>
						{/each}
					</dl>
				{:else}
					<p class="status">Stores nothing besides the link.</p>
				{/if}
			</div>
		{/each}
	{/if}
</div>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: max-content;
		max-width: 24rem;
		padding: var(--space-3);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-overlay);
		color: var(--color-text);
		font-size: var(--text-xs);
		line-height: var(--leading-ui);
	}
	p {
		margin: 0;
	}
	.kicker {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.title {
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	.ends {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.end {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		overflow-wrap: anywhere;
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
		flex: none;
	}
	.section {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding-top: var(--space-2);
		border-top: var(--border-hair) solid var(--color-line);
	}
	.rel {
		font-family: var(--font-mono);
		font-weight: var(--weight-semibold);
	}
	dl {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: var(--space-1) var(--space-3);
		margin: 0;
	}
	dt {
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		white-space: nowrap;
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.status {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
	}
	.status.error {
		color: var(--color-danger);
	}
	.status :global(.spin) {
		width: var(--space-4);
		height: var(--space-4);
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.status :global(.spin) {
			animation: none;
		}
	}
</style>
