<!--
@component
One count with its label. Pass a node `type` to key it to the graph legend colour.
Use a row of Stats as a summary above detail, never as decoration. Place Stats inside a <dl>.
-->
<script lang="ts">
	import type { NodeType } from '$lib/types';

	type Props = { label: string; value: number | string; type?: NodeType; note?: string };

	let { label, value, type, note }: Props = $props();
</script>

<div class="stat" style:--node={type ? `var(--node-${type})` : 'var(--color-line-strong)'}>
	<dt>
		<span class="dot" aria-hidden="true"></span>
		{label}
	</dt>
	<dd class="tabular">{value}</dd>
	{#if note}<dd class="note">{note}</dd>{/if}
</div>

<style>
	.stat {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	dt {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
	}
	dd {
		margin: 0;
		font-size: var(--text-3xl);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: var(--leading-tight);
	}
	.note {
		font-size: var(--text-xs);
		font-weight: var(--weight-regular);
		font-variation-settings: 'wdth' var(--width-body);
		color: var(--color-text-muted);
	}
</style>
