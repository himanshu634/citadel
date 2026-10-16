<!--
@component
The steps of a flow, in order (the add-company wizard). The current step is the one solid accent
block, with square corners; finished steps show a check in an ink circle; later steps show their
number. State is never colour alone: the check, the number and a screen-reader word say it.
-->
<script lang="ts">
	import { Check } from '@lucide/svelte';

	type Props = {
		steps: { label: string; hint?: string }[];
		/** Index of the current step. */
		current: number;
		/** Indexes of finished steps. */
		done: number[];
		/** Accessible name of the list. */
		label?: string;
	};

	let { steps, current, done, label = 'Progress' }: Props = $props();
</script>

<ol class="steps" aria-label={label}>
	{#each steps as step, i (step.label)}
		{@const isDone = i !== current && done.includes(i)}
		<li class={['step', { current: i === current, done: isDone }]} aria-current={i === current ? 'step' : undefined}>
			<span class="n" aria-hidden="true">
				{#if isDone}<Check />{:else}{i + 1}{/if}
			</span>
			<span class="text">
				<span class="name">{step.label}</span>
				{#if isDone}<span class="sr-only">(done)</span>{/if}
				{#if step.hint}<small>{step.hint}</small>{/if}
			</span>
		</li>
	{/each}
</ol>

<style>
	.steps {
		display: flex;
		flex-wrap: wrap;
		margin: 0;
		padding: 0;
		list-style: none;
		gap: var(--border-hair);
		/* The 1px gaps show this colour, which makes the dividers (also between wrapped rows). */
		background: var(--color-line);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.step {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex: 1 1 10rem;
		min-width: 0;
		min-height: var(--control-lg);
		padding: var(--space-2) var(--space-4);
		background: var(--color-surface);
		color: var(--color-text-muted);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		border-radius: var(--radius-none);
	}
	.n {
		display: grid;
		place-items: center;
		flex: none;
		width: 1.375rem;
		height: 1.375rem;
		border: var(--border-hair) solid currentColor;
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-body);
	}
	.n :global(svg) {
		width: 0.8125rem;
		height: 0.8125rem;
	}
	.text {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: 0 var(--space-3);
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	small {
		font-size: var(--text-xs);
		font-weight: var(--weight-regular);
		font-variation-settings: 'wdth' var(--width-body);
	}
	.done {
		color: var(--color-text);
	}
	.done .n {
		background: var(--color-text);
		border-color: var(--color-text);
		color: var(--color-surface);
	}
	.current {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
</style>
