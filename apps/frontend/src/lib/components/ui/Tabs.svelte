<!--
@component
Tabs on bits-ui. The selected tab is the solid accent block (the H signature), so the selected
state shows as fill plus weight, not colour alone. A tab can say it holds unsaved edits (a dot,
named for screen readers) and how many errors it holds (a count in words). Every panel stays
mounted and is only hidden, so what a person typed in one tab survives a switch.
-->
<script lang="ts">
	import { Tabs } from 'bits-ui';
	import type { Snippet } from 'svelte';

	type Props = {
		items: { value: string; label: string; count?: number; dirty?: boolean; errors?: number }[];
		value?: string;
		/** Accessible name for the tab list. */
		label: string;
		panel: Snippet<[string]>;
	};

	let { items, value = $bindable(items[0]?.value), label, panel }: Props = $props();
</script>

<Tabs.Root bind:value class="tabs">
	<Tabs.List class="tabs-list" aria-label={label}>
		{#each items as item (item.value)}
			<Tabs.Trigger value={item.value} class="tabs-trigger">
				{item.label}
				{#if item.count !== undefined}<span class="tabs-count tabular">{item.count}</span>{/if}
				{#if item.errors}
					<span class="tabs-errors tabular">{item.errors} {item.errors === 1 ? 'error' : 'errors'}</span>
				{/if}
				{#if item.dirty}
					<span class="tabs-dirty" aria-hidden="true"></span><span class="sr-only">(unsaved changes)</span>
				{/if}
			</Tabs.Trigger>
		{/each}
	</Tabs.List>
	{#each items as item (item.value)}
		<Tabs.Content value={item.value} class="tabs-panel">
			{@render panel(item.value)}
		</Tabs.Content>
	{/each}
</Tabs.Root>

<style>
	:global(.tabs) {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}
	:global(.tabs-list) {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		border-bottom: var(--border-hair) solid var(--color-line);
		padding-bottom: var(--space-2);
	}
	:global(.tabs-trigger) {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding-inline: var(--space-3);
		border: 0;
		border-radius: var(--radius-none);
		background: transparent;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	:global(.tabs-trigger:hover) {
		color: var(--color-text);
		background: var(--color-surface-sunken);
	}
	:global(.tabs-trigger[data-state='active']) {
		background: var(--color-accent);
		color: var(--color-on-accent);
		font-weight: var(--weight-semibold);
	}
	:global(.tabs-count) {
		font-size: var(--text-xs);
		opacity: 0.8;
	}
	:global(.tabs-errors) {
		padding: 0 var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-danger-soft);
		color: var(--color-danger);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
	}
	:global(.tabs-dirty) {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: currentColor;
	}
	:global(.tabs-panel:focus-visible) {
		outline-offset: 4px;
	}
</style>
