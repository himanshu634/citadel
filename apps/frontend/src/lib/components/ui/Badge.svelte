<!--
@component
Short status text. Tone carries meaning (success, warning, danger); `neutral` for plain facts.
Always readable without colour: the word itself states the status.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger';
		children: Snippet;
	};

	let { tone = 'neutral', children }: Props = $props();
</script>

<span class={['badge', tone]}>{@render children()}</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: 0.125rem var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		line-height: 1.4;
		white-space: nowrap;
	}
	.neutral {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
	}
	.accent {
		background: var(--color-accent-soft);
		color: var(--color-accent);
	}
	.success {
		background: var(--color-success-soft);
		color: var(--color-success);
	}
	.warning {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	.danger {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
</style>
