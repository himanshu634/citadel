<!--
@component
The brain's work for one answer, as a ledger (Ask page, direction J + L): one row per graph step
in plain words ("Read recent work on Auth"), with a mark for how it ended (done, running, found
nothing, failed, not run), the rows it returned and how long it took. A step that found nothing or
failed says so under its row and is never folded away. Once the answer is in (`settled`), repeated
calls of one tool fold into one row ("Read recent work on 4 systems: …"). Open a row to see the
call and its rows (`StepRows`). A node a sentence names ("Opened PR #10") opens on GitHub (or its
own site) in a new tab: the sentence sits beside the row's toggle, whose hit area covers the row,
and its links sit above that. Hovering or focusing a row reports its steps (`onhover`) so the
walk beside it can light what they added; leaving the list clears it. The last row is the newest
answer check; a pass after the answer was sent back says how many times. Rules in `ledgerItems`
and `checkLine` (src/lib/walk.ts).
-->
<script lang="ts">
	import { Check, ChevronRight, CircleAlert, CircleDashed, LoaderCircle, Minus } from '@lucide/svelte';
	import type { WalkStep } from '$lib/types';
	import { checkLine, ledgerItems, ledgerRuns, stepCall, type LedgerItem } from '$lib/walk';
	import RefText from '../ui/RefText.svelte';
	import StepRows from './StepRows.svelte';

	type Props = {
		steps: WalkStep[];
		/** The answer is in: repeated calls fold into one row. */
		settled?: boolean;
		/** The open row's key (its first step's id). */
		open?: string | null;
		ontoggle?: (key: string) => void;
		/** The steps of the row under the pointer or focus; null when it leaves. */
		onhover?: (steps: WalkStep[] | null) => void;
		/** Citation numbers by the uid they cite, to mark the rows they came from. */
		cites?: Map<string, number[]>;
		/** The citation being looked at. */
		active?: number | null;
	};

	let { steps, settled = false, open = null, ontoggle, onhover, cites = new Map(), active = null }: Props = $props();
	const id = $props.id();

	const items = $derived(ledgerItems(steps, settled));
	const keyOf = (item: LedgerItem) => item.steps[0].id;

	function meta(item: LedgerItem): string {
		if (item.state === 'running') return 'reading rows';
		if (item.state === 'failed') return 'failed';
		if (item.state === 'not-run') return 'not run';
		if (item.count === null) return '';
		return item.count === 1 ? '1 row' : `${item.count} rows`;
	}
	const checkState = $derived(checkLine(steps));
</script>

{#snippet mark(state: LedgerItem['state'])}
	<span class={['mark', state]} aria-hidden="true">
		{#if state === 'running'}<LoaderCircle class="spin" />
		{:else if state === 'failed'}<CircleAlert />
		{:else if state === 'empty'}<CircleDashed />
		{:else if state === 'not-run'}<Minus />
		{:else}<Check />{/if}
	</span>
{/snippet}

<!-- A row can fold away under a still pointer (no mouseleave), so leaving the list clears too. -->
<ol class="ledger" aria-label="What the brain did" onpointerleave={() => onhover?.(null)}>
	{#each items as item (keyOf(item))}
		{@const key = keyOf(item)}
		{@const isOpen = open === key}
		<li class={['item', item.state, { open: isOpen }]}>
			<!-- The toggle's ::after covers the row, so a click anywhere opens it; links sit above. -->
			<div
				class={['row', { live: item.state !== 'running' }]}
				role="presentation"
				onmouseenter={() => onhover?.(item.steps)}
				onmouseleave={() => onhover?.(null)}
			>
				{@render mark(item.state)}
				<span class="sentence" id="{id}-{key}-s"><RefText runs={ledgerRuns(item)} /></span>
				<span class="meta tabular">{meta(item)}</span>
				<span class="ms tabular">{item.ms != null ? `${item.ms} ms` : ''}</span>
				<button
					type="button"
					class="toggle"
					aria-expanded={isOpen}
					aria-controls="{id}-{key}"
					aria-labelledby="{id}-{key}-s"
					disabled={item.state === 'running'}
					onclick={() => ontoggle?.(key)}
					onfocus={() => onhover?.(item.steps)}
					onblur={() => onhover?.(null)}
				>
					<ChevronRight class="chev" aria-hidden="true" />
				</button>
			</div>
			{#if item.state === 'empty'}
				<p class="why empty">Found nothing.</p>
			{:else if item.state === 'failed'}
				<p class="why failed">{item.steps[0].error}</p>
			{:else if item.state === 'not-run'}
				<p class="why">The answer ended before this call ran.</p>
			{/if}
			{#if isOpen}
				<div id="{id}-{key}" class="detail">
					{#each item.steps as step (step.id)}
						<p class="call">{step.n}. {stepCall(step)}</p>
						<StepRows {step} {cites} {active} />
					{/each}
				</div>
			{/if}
		</li>
	{:else}
		{#if !settled}<li class="item waiting"><span class="sentence">Reading the question</span></li>{/if}
	{/each}
	{#if checkState}
		<li class={['item', 'check', checkState.state]}>
			<span class="row static">
				{@render mark(checkState.state)}
				<span class="sentence">{checkState.text}</span>
			</span>
		</li>
	{/if}
</ol>

<style>
	.ledger {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.item {
		border-radius: var(--radius-md);
		animation: arrive var(--duration-base) var(--ease-out);
	}
	.item.open {
		background: var(--color-surface);
		padding-bottom: var(--space-2);
	}
	.row {
		position: relative;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: var(--control-md);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-md);
		color: var(--color-text);
		text-align: left;
	}
	.row.live {
		cursor: pointer;
	}
	.row.live:hover {
		background: var(--color-surface-sunken);
	}
	.toggle {
		display: grid;
		flex: none;
		place-items: center;
		padding: 0;
		border: 0;
		background: none;
		color: inherit;
		cursor: inherit;
	}
	/* The toggle's hit area is the whole row; its focus ring draws round the row too. */
	.toggle::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: var(--radius-md);
	}
	.toggle:focus-visible {
		outline: none;
	}
	.toggle:focus-visible::after {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: -2px;
	}
	/* Links in the sentence sit above the toggle's hit area. */
	.sentence :global(a) {
		position: relative;
		z-index: 1;
	}
	.mark {
		display: grid;
		flex: none;
		place-items: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: var(--radius-full);
		background: var(--color-success-soft);
		color: var(--color-success);
	}
	.mark :global(svg) {
		width: 0.8rem;
		height: 0.8rem;
	}
	.mark.running {
		background: none;
		color: var(--color-accent);
	}
	.mark.running :global(svg) {
		width: 1.1rem;
		height: 1.1rem;
	}
	.mark.failed {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	.mark.empty {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	.mark.not-run {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
	}
	.sentence {
		flex: 1;
		min-width: 0;
		font-size: var(--text-md);
		overflow-wrap: anywhere;
	}
	.running .sentence {
		color: var(--color-accent);
	}
	.meta,
	.ms {
		flex: none;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		white-space: nowrap;
	}
	.ms {
		min-width: 3rem;
		font-family: var(--font-mono);
		text-align: right;
	}
	.row :global(.chev) {
		flex: none;
		width: 1rem;
		height: 1rem;
		color: var(--color-text-muted);
		transition: transform var(--duration-fast) var(--ease-out);
	}
	.toggle:disabled :global(.chev) {
		visibility: hidden;
	}
	.open .row :global(.chev) {
		transform: rotate(90deg);
	}
	.why {
		margin: calc(-1 * var(--space-1)) 0 var(--space-1);
		padding-left: calc(var(--space-2) + 1.25rem + var(--space-3));
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.why.empty {
		color: var(--color-warning);
	}
	.why.failed {
		color: var(--color-danger);
	}
	.detail {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: 0 var(--space-2) 0 calc(var(--space-2) + 1.25rem + var(--space-3));
	}
	.call {
		padding-top: var(--space-1);
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
	.waiting .sentence {
		display: block;
		padding: var(--space-2);
		color: var(--color-text-muted);
	}
	.check .sentence {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.check.failed .sentence {
		color: var(--color-danger);
	}
	@keyframes arrive {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.item {
			animation: none;
		}
		.row :global(.chev) {
			transition: none;
		}
	}
</style>
