<!--
@component
The chain of graph hops behind an answer: node, RELATIONSHIP, node. Every answer shows one.
Relationship names stay in the schema's own UPPER_CASE so they match Cypher.
-->
<script lang="ts">
	import NodeChip from '$lib/components/ui/NodeChip.svelte';
	import type { PathStep } from '$lib/types';

	type Props = { steps: PathStep[]; label?: string };

	let { steps, label = 'Graph path' }: Props = $props();
</script>

<ol class="path" aria-label={label}>
	{#each steps as step (step.node.uid)}
		<li>
			<NodeChip type={step.node.type} label={step.node.label} />
			{#if step.edge}<span class="edge">{step.edge}</span>{/if}
		</li>
	{/each}
</ol>

<style>
	.path {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.edge {
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		letter-spacing: 0.02em;
	}
</style>
