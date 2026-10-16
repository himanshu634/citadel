<!--
@component
A short hint on hover or focus. Never put the only copy of important information in a tooltip.
The trigger is rendered by you through the `child` snippet, with the props spread onto it.
`detail` adds a second line in mono for an id such as a graph name. `disabled` keeps the trigger
but never opens (the folding sidebar keeps one markup and names its items only while folded).
It fades and slides in a few pixels from its trigger; it closes at once.
Needs a <Tooltip.Provider> above it (AppShell provides one).
-->
<script lang="ts">
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';

	type Props = {
		text: string;
		detail?: string;
		side?: 'top' | 'right' | 'bottom' | 'left';
		disabled?: boolean;
		trigger: Snippet<[Record<string, unknown>]>;
	};

	let { text, detail, side = 'top', disabled = false, trigger }: Props = $props();
	// Disabling closes it too: a tooltip open under the pointer must not outlive the fold.
	let open = $state(false);
	$effect.pre(() => {
		if (disabled) open = false;
	});
</script>

<Tooltip.Root {disabled} bind:open>
	<Tooltip.Trigger>
		{#snippet child({ props })}
			{@render trigger(props)}
		{/snippet}
	</Tooltip.Trigger>
	<Tooltip.Portal>
		<Tooltip.Content {side} sideOffset={6} class="tooltip">
			<span class="name">{text}</span>
			{#if detail}<code class="detail">{detail}</code>{/if}
		</Tooltip.Content>
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
		overflow-wrap: anywhere;
		animation: tooltip-in var(--duration-fast) var(--ease-out);
	}
	/* From the trigger's side: bits-ui puts the side it opened on in data-side. */
	:global(.tooltip[data-side='right']) {
		--tooltip-from: translateX(calc(-1 * var(--space-1)));
	}
	:global(.tooltip[data-side='left']) {
		--tooltip-from: translateX(var(--space-1));
	}
	:global(.tooltip[data-side='bottom']) {
		--tooltip-from: translateY(calc(-1 * var(--space-1)));
	}
	@keyframes tooltip-in {
		from {
			opacity: 0;
			transform: var(--tooltip-from, translateY(var(--space-1)));
		}
	}
	:global(.tooltip .name),
	:global(.tooltip .detail) {
		display: block;
	}
	:global(.tooltip .detail) {
		font-size: var(--text-xs);
	}
</style>
