<!--
@component
A person, team or system in a list: avatar in its node colour, name, one line of context, and
an optional trailing value (a count). Pass `selected` for the row whose detail is open.
-->
<script lang="ts">
	import Avatar from '$lib/components/ui/Avatar.svelte';
	import type { NodeType } from '$lib/types';

	type Props = {
		name: string;
		type: NodeType;
		meta?: string;
		value?: string | number;
		valueLabel?: string;
		selected?: boolean;
		href?: string;
	};

	let { name, type, meta, value, valueLabel, selected = false, href }: Props = $props();
</script>

<svelte:element
	this={href ? 'a' : 'div'}
	{href}
	class={['row', { selected }]}
	aria-current={selected && href ? 'true' : undefined}
>
	<Avatar {name} {type} />
	<span class="main">
		<span class="name">{name}</span>
		{#if meta}<span class="meta">{meta}</span>{/if}
	</span>
	{#if value !== undefined}
		<span class="value tabular">
			{value}
			{#if valueLabel}<span class="sr-only">{valueLabel}</span>{/if}
		</span>
	{/if}
</svelte:element>

<style>
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--control-lg);
		padding: var(--space-2);
		border-radius: var(--radius-md);
		color: var(--color-text);
		text-decoration: none;
		min-width: 0;
	}
	a.row:hover {
		background: var(--color-surface-sunken);
	}
	.selected {
		background: var(--color-accent-soft);
	}
	a.selected:hover {
		background: var(--color-accent-soft);
	}
	.main {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
		line-height: var(--leading-tight);
	}
	.name {
		font-weight: var(--weight-semibold);
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.value {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
