<!--
@component
Dropdown menu on bits-ui (keyboard navigation, typeahead, Escape to close).
Items with `selected` show a check, for picking one of a set (company switcher, sort order).
-->
<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { Check } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import type { MenuItem } from '$lib/types';

	type Props = {
		items: MenuItem[];
		heading?: string;
		onselect: (value: string) => void;
		trigger: Snippet<[Record<string, unknown>]>;
		align?: 'start' | 'end';
	};

	let { items, heading, onselect, trigger, align = 'start' }: Props = $props();
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			{@render trigger(props)}
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Portal>
		<DropdownMenu.Content class="menu" {align} sideOffset={6}>
			<DropdownMenu.Group>
				{#if heading}
					<DropdownMenu.GroupHeading class="menu-heading">{heading}</DropdownMenu.GroupHeading>
				{/if}
				{#each items as item (item.value)}
					<DropdownMenu.Item class="menu-item" onSelect={() => onselect(item.value)}>
						<span class="menu-check" aria-hidden="true">
							{#if item.selected}<Check />{/if}
						</span>
						<span class="menu-label">
							{item.label}
							{#if item.hint}<small>{item.hint}</small>{/if}
						</span>
						{#if item.selected}<span class="sr-only">(selected)</span>{/if}
					</DropdownMenu.Item>
				{/each}
			</DropdownMenu.Group>
		</DropdownMenu.Content>
	</DropdownMenu.Portal>
</DropdownMenu.Root>

<style>
	/* The panel takes focus on open; its items show focus, so the panel itself needs no ring. */
	:global(.menu:focus-visible) {
		outline: none;
	}
	:global(.menu) {
		z-index: 50;
		min-width: 14rem;
		padding: var(--space-1);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	:global(.menu-heading) {
		padding: var(--space-2) var(--space-3) var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	:global(.menu-item) {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-md);
		padding: var(--space-1) var(--space-3) var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
		outline: none;
	}
	:global(.menu-item[data-highlighted]) {
		background: var(--color-accent-soft);
	}
	:global(.menu-check) {
		display: grid;
		place-items: center;
		width: 1rem;
		color: var(--color-accent);
	}
	:global(.menu-check svg) {
		width: 1rem;
		height: 1rem;
	}
	:global(.menu-label) {
		display: flex;
		flex-direction: column;
		line-height: var(--leading-tight);
	}
	:global(.menu-label small) {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
</style>
