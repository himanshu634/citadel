<!--
@component
A short hint on hover or focus. Never put the only copy of important information in a tooltip.
The trigger is rendered by you through the `child` snippet, with the props spread onto it.
Needs a <Tooltip.Provider> above it (AppShell provides one).
-->
<script lang="ts">
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';

	type Props = {
		text: string;
		side?: 'top' | 'right' | 'bottom' | 'left';
		trigger: Snippet<[Record<string, unknown>]>;
	};

	let { text, side = 'top', trigger }: Props = $props();
</script>

<Tooltip.Root>
	<Tooltip.Trigger>
		{#snippet child({ props })}
			{@render trigger(props)}
		{/snippet}
	</Tooltip.Trigger>
	<Tooltip.Portal>
		<Tooltip.Content {side} sideOffset={6} class="tooltip">{text}</Tooltip.Content>
	</Tooltip.Portal>
</Tooltip.Root>

<style>
	:global(.tooltip) {
		z-index: 50;
		max-width: 16rem;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-text);
		color: var(--color-surface);
		font-size: var(--text-xs);
		line-height: var(--leading-ui);
	}
</style>
