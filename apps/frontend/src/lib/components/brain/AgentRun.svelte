<!--
@component
One agent run as the Systems page's rail lists it (design direction A): what the run was for,
then every step in order, numbered as on the map. A step with a point on the map has a solid ink
number; the step running now has a ring; a step spread over several territories (listing the
systems) says "across the graph"; a step that touched nothing the map draws (the answer check, an
MCP call) has a dash and says so. A node a step names ("Opened PR #10") opens on GitHub (or its
own site) in a new tab. Links to the chat an Ask run came from.
-->
<script lang="ts">
	import { ArrowUpRight } from '@lucide/svelte';
	import { actorName, stepLineRuns, stepsSummary, type Trail } from '$lib/activity';
	import RefText from '../ui/RefText.svelte';
	import { ago } from '$lib/time';
	import type { ActivityRun } from '$lib/types';

	type Props = {
		run: ActivityRun;
		trail: Trail;
		/** Where the run can be read in full (an Ask run's chat). */
		href?: string | null;
		/** For tests and the gallery: the clock relative times read. */
		now?: number;
		/** Where a node opens, by uid (the graph's urls); GitHub uids open on github.com anyway. */
		urlOf?: (uid: string) => string | null;
	};

	let { run, trail, href = null, now, urlOf }: Props = $props();

	const placed = $derived(new Set(trail.points.flatMap((p) => p.ns)));
	const going = $derived(run.status === 'running');
	const STATUS: Record<ActivityRun['status'], string> = {
		running: 'Working now',
		done: 'Done',
		stopped: 'Stopped',
		failed: 'Failed'
	};
</script>

<section class="run" aria-label="Agent run">
	<p class="eyebrow">
		{going ? `${actorName(run.actor)} is working on` : `${actorName(run.actor)}, ${ago(run.started_at, now)}`}
	</p>
	<h2>{run.title}</h2>
	<p class="meta">
		<span class={['status', run.status]}>{STATUS[run.status]}</span>
		<span>{stepsSummary(run, trail)}</span>
	</p>

	{#if run.steps.length === 0}
		<p class="none">{going ? 'Reading the question. The first step shows here.' : 'This run took no steps.'}</p>
	{:else}
		<ol>
			{#each run.steps as step (step.n)}
				{@const on = placed.has(step.n)}
				{@const across = trail.spread.has(step.n)}
				<li class={{ off: !on }}>
					<span
						class={['n', { now: step.status === 'running', off: !on && step.status !== 'running' }]}
						aria-hidden="true">{on || step.status === 'running' ? step.n : '–'}</span
					>
					<div class="body">
						<span class="line"><RefText runs={stepLineRuns(step, urlOf)} /></span>
						<span class="sub">
							<code>{step.tool}</code>
							{#if step.error}<span class="error">{step.error}</span>
							{:else if step.status === 'running'}running
							{:else if step.count !== null}{step.count} {step.count === 1 ? 'row' : 'rows'}{/if}
							{#if across}<span>across the graph</span>
							{:else if !on && step.status !== 'running'}<span>not on the map</span>{/if}
						</span>
					</div>
				</li>
			{/each}
		</ol>
	{/if}

	{#if href}
		<a class="open" {href}>Open the chat <ArrowUpRight aria-hidden="true" /></a>
	{/if}
</section>

<style>
	.run {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.eyebrow {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		line-height: var(--leading-tight);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.status {
		padding: 0 var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		color: var(--color-text);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		line-height: 1.6;
	}
	.status.running {
		background: var(--color-text);
		color: var(--color-surface);
	}
	.status.failed {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	.none {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	ol {
		display: flex;
		flex-direction: column;
		margin: var(--space-2) 0 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-top: var(--border-hair) solid var(--color-line);
	}
	.n {
		flex: none;
		min-width: var(--space-5);
		height: var(--space-5);
		padding: 0 var(--space-1);
		box-sizing: border-box;
		border-radius: var(--radius-full);
		background: var(--color-text);
		color: var(--color-surface);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		line-height: var(--space-5);
		text-align: center;
	}
	.n.now {
		background: transparent;
		border: var(--border-focus) solid var(--color-text);
		color: var(--color-text);
		line-height: calc(var(--space-5) - 2 * var(--border-focus));
	}
	.n.off {
		background: transparent;
		color: var(--color-text-faint);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.line {
		font-size: var(--text-md);
		overflow-wrap: anywhere;
	}
	.sub {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	code {
		font-family: var(--font-mono);
	}
	.error {
		color: var(--color-danger);
	}
	.open {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		align-self: flex-start;
		margin-top: var(--space-2);
		color: var(--color-accent);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
	}
	.open :global(svg) {
		width: 1em;
		height: 1em;
	}
</style>
