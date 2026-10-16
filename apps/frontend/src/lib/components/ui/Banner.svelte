<!--
@component
A status line across the top of a view: what state the page is in and, in `action`, the one thing
to do about it. Tone carries meaning (warning, danger, neutral) but the icon and the title say it
too, so it never relies on colour. Pass `icon` when a state has its own mark (a spinner for a build
in progress); the default is the tone's. It is announced politely (`role="status"`).
-->
<script lang="ts">
	import { CircleAlert, Info, TriangleAlert } from '@lucide/svelte';
	import type { Component, Snippet } from 'svelte';

	type Props = {
		tone: 'warning' | 'danger' | 'neutral';
		title: string;
		/** Overrides the tone's icon. */
		icon?: Component;
		/** Turn the icon (a build in progress); stops under reduced motion. */
		spin?: boolean;
		children?: Snippet;
		action?: Snippet;
	};

	let { tone, title, icon, spin = false, children, action }: Props = $props();

	const Icon = $derived(
		icon ?? (tone === 'danger' ? CircleAlert : tone === 'warning' ? TriangleAlert : Info)
	);
</script>

<div class={['banner', tone]} role="status">
	<Icon class={['mark', { spin }]} aria-hidden="true" />
	<div class="text">
		<p class="title">{title}</p>
		{#if children}<div class="body">{@render children()}</div>{/if}
	</div>
	{#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
	.banner {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border: var(--border-hair) solid var(--tone);
		border-radius: var(--radius-md);
		background: var(--tone-soft);
		min-width: 0;
	}
	.warning {
		--tone: var(--color-warning);
		--tone-soft: var(--color-warning-soft);
	}
	.danger {
		--tone: var(--color-danger);
		--tone-soft: var(--color-danger-soft);
	}
	.neutral {
		--tone: var(--color-line-strong);
		--tone-soft: var(--color-surface-sunken);
	}
	.banner :global(.mark) {
		width: 1.25rem;
		height: 1.25rem;
		flex: none;
		color: var(--tone);
	}
	.neutral :global(.mark) {
		color: var(--color-text-muted);
	}
	.text {
		min-width: 0;
	}
	.title {
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.body {
		margin-top: var(--space-1);
		color: var(--color-text);
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
		white-space: pre-line;
	}
	/* Narrow: the action drops under the text, in the text's column. */
	@media (max-width: 40rem) {
		.action {
			grid-column: 2;
		}
	}
	.banner :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.banner :global(.spin) {
			animation: none;
		}
	}
</style>
