<!--
@component
The tool calls behind one answer, in order: each graph step with its call, how many rows came
back and how long it took; failed steps say why; the last row is the answer check (the answer may
cite only what the steps returned). Open a step to see the rows it returned; rows a citation used
carry that citation's number, and the active citation's rows are tinted. Paths read as chains.
-->
<script lang="ts">
	import { Check, ChevronRight, CircleAlert, LoaderCircle } from '@lucide/svelte';
	import type { WalkStep } from '$lib/types';
	import { stepCall } from '$lib/walk';
	import StepRows from './StepRows.svelte';

	type Props = {
		steps: WalkStep[];
		/** The open step's id. */
		open?: string | null;
		ontoggle?: (id: string) => void;
		/** Citation numbers by the uid they cite, to mark the rows they came from. */
		cites?: Map<string, number[]>;
		/** The citation being looked at. */
		active?: number | null;
	};

	let { steps, open = null, ontoggle, cites = new Map(), active = null }: Props = $props();
	const id = $props.id();

	const notRun = (step: WalkStep) => step.error?.startsWith('Not run') ?? false;
	function meta(step: WalkStep): string {
		if (step.status === 'running') return 'running';
		if (notRun(step)) return 'not run';
		if (step.error) return 'failed';
		if (step.count == null) return 'not run';
		return step.count === 1 ? '1 row' : `${step.count} rows`;
	}
</script>

<ol class="steps">
	{#each steps as step (step.id)}
		{@const failed = !!step.error}
		{#if step.n === null}
			<li class={['check', { failed }]}>
				<span class="mark" aria-hidden="true">
					{#if failed}<CircleAlert />{:else if step.status === 'running'}<LoaderCircle class="spin" />{:else}<Check />{/if}
				</span>
				<div class="what">
					<span class="call">Answer check</span>
					<span class="meta">
						{#if step.status === 'running'}checking the citations
						{:else if notRun(step)}not run: the answer ended first
						{:else if failed}sent back: {step.error}
						{:else}every citation was returned by a step above{/if}
					</span>
				</div>
			</li>
		{:else}
			{@const isOpen = open === step.id}
			<li class={['step', step.status, { failed, open: isOpen }]}>
				<button
					type="button"
					class="head"
					aria-expanded={isOpen}
					aria-controls="{id}-{step.id}"
					disabled={step.status === 'running'}
					onclick={() => ontoggle?.(step.id)}
				>
					<span class="n tabular" aria-hidden="true">
						{#if step.status === 'running'}<LoaderCircle class="spin" />{:else if failed}<CircleAlert />{:else}{step.n}{/if}
					</span>
					<span class="sr-only">Step {step.n}:</span>
					<span class="call">{stepCall(step)}</span>
					<span class="meta">{meta(step)}</span>
					{#if step.ms != null}<span class="ms tabular">{step.ms} ms</span>{/if}
					<ChevronRight class="chev" aria-hidden="true" />
				</button>
				{#if failed}
					<p class="error">{step.error}</p>
				{/if}
				{#if isOpen}
					<div id="{id}-{step.id}" class="rows">
						<StepRows {step} {cites} {active} />
					</div>
				{/if}
			</li>
		{/if}
	{/each}
</ol>

<style>
	.steps {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.step.open {
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		outline: var(--border-hair) solid var(--color-line-strong);
		padding-bottom: var(--space-2);
	}
	.head,
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: var(--control-md);
		padding: var(--space-1) var(--space-3);
		border: 0;
		border-radius: var(--radius-md);
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
	}
	.head:not(:disabled) {
		cursor: pointer;
	}
	.head:not(:disabled):hover {
		background: var(--color-surface-sunken);
	}
	.n,
	.mark {
		display: grid;
		flex: none;
		place-items: center;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: var(--radius-full);
		background: var(--color-success-soft);
		color: var(--color-success);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.n :global(svg),
	.mark :global(svg) {
		width: 0.875rem;
		height: 0.875rem;
	}
	.running .n {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.failed .n,
	.check.failed .mark {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	.call {
		overflow: hidden;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.check .what {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.check .call {
		font-family: inherit;
	}
	.meta {
		flex: none;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.check .meta {
		flex: initial;
	}
	.running .meta {
		color: var(--color-accent);
	}
	.ms {
		margin-left: auto;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		white-space: nowrap;
	}
	.head :global(.chev) {
		flex: none;
		width: 1rem;
		height: 1rem;
		margin-left: var(--space-1);
		color: var(--color-text-muted);
		transition: transform var(--duration-fast) var(--ease-out);
	}
	.head:not(:has(.ms)) :global(.chev) {
		margin-left: auto;
	}
	.head:disabled :global(.chev) {
		visibility: hidden;
	}
	.open .head :global(.chev) {
		transform: rotate(90deg);
	}
	.error {
		padding: 0 var(--space-3) var(--space-2) calc(var(--space-3) * 2 + 1.5rem);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.rows {
		padding: 0 var(--space-2) 0 calc(var(--space-3) * 2 + 1.5rem);
	}
	@media (prefers-reduced-motion: reduce) {
		.head :global(.chev) {
			transition: none;
		}
	}
</style>
