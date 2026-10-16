<!--
@component
A panel on the stone ground. Give it a `title` to get the standard wide header; `actions`
renders on the right of that header. Cards never nest and never cast a shadow.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		title?: string;
		/** Short line under the title: what the card shows, or its time window. */
		description?: string;
		actions?: Snippet;
		padded?: boolean;
		children: Snippet;
		class?: string;
	};

	let { title, description, actions, padded = true, children, class: className }: Props = $props();
	const headingId = $props.id();
</script>

<section class={['card', className]} aria-labelledby={title ? headingId : undefined}>
	{#if title}
		<header>
			<div class="titles">
				<h2 id={headingId}>{title}</h2>
				{#if description}<p>{description}</p>{/if}
			</div>
			{#if actions}<div class="actions">{@render actions()}</div>{/if}
		</header>
	{/if}
	<div class={['body', { padded }]}>
		{@render children()}
	</div>
</section>

<style>
	.card {
		display: flex;
		flex-direction: column;
		min-width: 0;
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-4) var(--space-5) 0;
	}
	.titles {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	h2 {
		font-size: var(--text-md);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	header p {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		flex: none;
	}
	.body {
		min-width: 0;
	}
	.padded {
		padding: var(--space-4) var(--space-5) var(--space-5);
	}
</style>
