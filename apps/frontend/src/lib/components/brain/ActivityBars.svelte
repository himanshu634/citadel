<!--
@component
Horizontal bars comparing one count across a few items (changes per system). Bars share one
scale starting at zero; the number is printed, so the bar is never the only way to read it.
-->
<script lang="ts">
	import type { NodeType } from '$lib/types';

	type Props = {
		items: { label: string; value: number; meta?: string }[];
		type?: NodeType;
		unit: string;
	};

	let { items, type = 'system', unit }: Props = $props();
	const max = $derived(Math.max(1, ...items.map((i) => i.value)));
</script>

<ul class="bars" style:--node="var(--node-{type})">
	{#each items as item (item.label)}
		<li>
			<div class="label">
				<span class="name">{item.label}</span>
				{#if item.meta}<span class="meta">{item.meta}</span>{/if}
			</div>
			<div class="track" aria-hidden="true">
				<span class="fill" style:width="{(item.value / max) * 100}%"></span>
			</div>
			<span class="value tabular">{item.value}<span class="sr-only"> {unit}</span></span>
		</li>
	{/each}
</ul>

<style>
	.bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: grid;
		grid-template-columns: minmax(6rem, 9rem) 1fr 2rem;
		align-items: center;
		gap: var(--space-3);
	}
	.label {
		display: flex;
		flex-direction: column;
		min-width: 0;
		line-height: var(--leading-tight);
	}
	.name {
		font-weight: var(--weight-medium);
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.track {
		height: 0.625rem;
		background: var(--color-surface-sunken);
	}
	.fill {
		display: block;
		height: 100%;
		background: var(--node);
	}
	.value {
		text-align: right;
		font-weight: var(--weight-semibold);
	}
</style>
