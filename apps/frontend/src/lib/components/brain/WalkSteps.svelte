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
	import { rowViews, stepCall } from '$lib/walk';

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

	function citesOf(uids: string[]): number[] {
		return [...new Set(uids.flatMap((u) => cites.get(u) ?? []))].sort((a, b) => a - b);
	}
	function meta(step: WalkStep): string {
		if (step.status === 'running') return 'running';
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
						{:else if failed}sent back: {step.error}
						{:else}every citation was returned by a step above{/if}
					</span>
				</div>
			</li>
		{:else}
			{@const isOpen = open === step.id}
			{@const rows = isOpen ? rowViews(step) : []}
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
						{#if rows.length === 0}
							<p class="none">No rows. The graph has nothing that matches this call.</p>
						{:else}
							<ul>
								{#each rows as row, i (i)}
									{@const used = citesOf(row.uids)}
									<li class={{ hl: active !== null && used.includes(active) }}>
										{#if row.chain}
											<span class="chain">
												{#each row.chain as link, j (j)}
													<span class="hop">{link.title}</span>
													{#if link.rel}<span class="rel">{link.forward ? '' : '← '}{link.rel}{link.forward ? ' →' : ''}</span>{/if}
												{/each}
											</span>
										{:else}
											<span class="text">{row.text}</span>
										{/if}
										{#each used as n (n)}<span class={['cite', { on: n === active }]} aria-label="cited as {n}">{n}</span>{/each}
									</li>
								{/each}
							</ul>
							{#if (step.count ?? 0) > rows.length}
								<p class="none">and {(step.count ?? 0) - rows.length} more rows the agent read</p>
							{/if}
						{/if}
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
	.rows ul {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 14rem;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		list-style: none;
	}
	.rows li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
	.rows li.hl {
		background: var(--color-accent-soft);
	}
	.chain,
	.text {
		display: flex;
		flex: 1;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.rel {
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.cite {
		flex: none;
		min-width: 1.25rem;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-accent-soft);
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		text-align: center;
	}
	.cite:first-of-type {
		margin-left: auto;
	}
	.cite.on {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.none {
		padding: var(--space-1) var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	@media (prefers-reduced-motion: reduce) {
		.head :global(.chev) {
			transition: none;
		}
	}
</style>
