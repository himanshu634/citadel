<!--
@component
A graph node reference: a coloured dot for its type plus its label. The type is also in the
accessible name, so colour is never the only signal.
-->
<script lang="ts">
	import { NODE_LABELS, type NodeType } from '$lib/types';

	type Props = { type: NodeType; label: string; href?: string };

	let { type, label, href }: Props = $props();
</script>

<svelte:element
	this={href ? 'a' : 'span'}
	{href}
	class="chip"
	style:--node="var(--node-{type})"
	title={NODE_LABELS[type]}
>
	<span class="dot" aria-hidden="true"></span>
	<span class="sr-only">{NODE_LABELS[type]}:</span>
	{label}
</svelte:element>

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: 0.125rem var(--space-3) 0.125rem var(--space-2);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-full);
		background: var(--color-surface);
		color: var(--color-text);
		font-size: var(--text-sm);
		line-height: 1.5;
		text-decoration: none;
		white-space: nowrap;
	}
	a.chip:hover {
		border-color: var(--node);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
		flex: none;
	}
</style>
