<!--
@component
What to show when a list or view has nothing yet. Say what will appear here and how to get it;
put that one action in `action`.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = { title: string; description: string; icon?: Snippet; action?: Snippet };

	let { title, description, icon, action }: Props = $props();
</script>

<div class="empty">
	{#if icon}<div class="icon" aria-hidden="true">{@render icon()}</div>{/if}
	<h3>{title}</h3>
	<p>{description}</p>
	{#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
	.empty {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-6);
		border: var(--border-hair) dashed var(--color-line-strong);
		border-radius: var(--radius-md);
	}
	.icon {
		color: var(--color-text-muted);
	}
	.icon :global(svg) {
		width: 1.5rem;
		height: 1.5rem;
	}
	h3 {
		font-size: var(--text-lg);
	}
	p {
		max-width: 52ch;
		color: var(--color-text-muted);
	}
	.action {
		padding-top: var(--space-2);
	}
</style>
