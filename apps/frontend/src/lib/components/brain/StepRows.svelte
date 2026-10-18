<!--
@component
The rows one graph step returned, as `WalkSteps` and `WalkLedger` list them when a step is open:
paths read as chains of nodes and relationships, other rows as one line (`rowViews`). Rows a
citation used carry its number, and the rows of the active citation are tinted. A row or hop whose
node has a page (a PR, issue, commit, document) links to it, in a new tab. Says so when the step
found nothing, and how many more rows the agent read than are shown.
-->
<script lang="ts">
	import type { WalkStep } from '$lib/types';
	import { rowViews } from '$lib/walk';
	import RefLink from '../ui/RefLink.svelte';

	type Props = {
		step: WalkStep;
		/** Citation numbers by the uid they cite. */
		cites?: Map<string, number[]>;
		/** The citation being looked at. */
		active?: number | null;
	};

	let { step, cites = new Map(), active = null }: Props = $props();

	const rows = $derived(rowViews(step));
	function citesOf(uids: string[]): number[] {
		return [...new Set(uids.flatMap((u) => cites.get(u) ?? []))].sort((a, b) => a - b);
	}
</script>

{#if rows.length === 0}
	<p class="none">No rows. The graph has nothing that matches this call.</p>
{:else}
	<ul>
		{#each rows as row, i (i)}
			{@const used = citesOf(row.uids)}
			<li class={{ hl: active !== null && used.includes(active) }}>
				{#if row.chain}
					<span class="chain">
						{#each row.chain as link, j (j)}
							<span class="hop">{#if link.url}<RefLink href={link.url}>{link.title}</RefLink>{:else}{link.title}{/if}</span>
							{#if link.rel}<span class="rel">{link.forward ? '' : '← '}{link.rel}{link.forward ? ' →' : ''}</span>{/if}
						{/each}
					</span>
				{:else}
					<span class="text">{#if row.url}<RefLink href={row.url}>{row.text}</RefLink>{:else}{row.text}{/if}</span>
				{/if}
				{#each used as n (n)}<span class={['cite', { on: n === active }]}><span class="sr-only">cited as </span>{n}</span>{/each}
			</li>
		{/each}
	</ul>
	{#if (step.count ?? 0) > rows.length}
		<p class="none">and {(step.count ?? 0) - rows.length} more rows the agent read</p>
	{/if}
{/if}

<style>
	ul {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 14rem;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		list-style: none;
	}
	li {
		display: flex;
		/* The list scrolls: a wrapped row keeps its height instead of shrinking under the next. */
		flex: none;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
	li.hl {
		background: var(--color-accent-soft);
	}
	.chain,
	.text {
		display: flex;
		flex: 1;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.rel {
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.cite {
		flex: none;
		min-width: 1.25rem;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-accent-soft);
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		text-align: center;
	}
	.cite:first-of-type {
		margin-left: auto;
	}
	.cite.on {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.none {
		padding: var(--space-1) var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
