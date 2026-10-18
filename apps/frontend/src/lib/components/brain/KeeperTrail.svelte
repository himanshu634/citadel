<!--
@component
How the Keeper got to one claim, as the review page's detail shows it under the gap: which review
wrote it, then each agent's job in the order it ran. pm and qa each drafted an answer (quoted, with
the uids they cited) or said they could not ground it; the Keeper checked the drafts and wrote the
claim, with its own reasoning from the log. Every job's graph reads open under it, one line each
as on the Systems page. A claim no review wrote (a person's reply in Ask) shows the gap's log
instead. `trail` is null while it loads; `failed` says it could not be read.
-->
<script lang="ts">
	import { actorName, stepLineRuns } from '$lib/activity';
	import {
		keeperReasoning,
		logSentence,
		logTime,
		logWhy,
		trailHeading,
		trailJobTitle,
		trailLog,
		trailSummary,
		type EvidenceRef
	} from '$lib/keeper';
	import type { ClaimTrail } from '$lib/types';
	import { nodeType } from '$lib/walk';
	import NodeChip from '../ui/NodeChip.svelte';
	import RefText from '../ui/RefText.svelte';

	type Props = {
		trail: ClaimTrail | null;
		/** The trail could not be read: the message to show. */
		failed?: string | null;
		/** Uids named as well as the page knows them, for the chips of what pm and qa cited. */
		refsOf: (uids: string[]) => EvidenceRef[];
		/** Where a node opens, by uid. */
		urlOf?: (uid: string) => string | null;
		/** For tests and the gallery: the clock times read. */
		now?: number;
	};

	let { trail, failed = null, refsOf, urlOf, now }: Props = $props();
	const id = $props.id();

	const reasoning = $derived(trail ? keeperReasoning(trail.log) : null);
	const lines = $derived(trail ? trailLog(trail.log) : []);
	const LABEL_MAX = 32;
	const short = (text: string) => (text.length > LABEL_MAX ? `${text.slice(0, LABEL_MAX - 1)}…` : text);
</script>

<section class="trail" aria-labelledby="{id}-h">
	<h3 id="{id}-h">How the Keeper got here</h3>
	{#if failed}
		<p class="none">Can't read the Keeper's work on this claim: {failed}</p>
	{:else if !trail}
		<p class="none" aria-busy="true">Reading the Keeper's work…</p>
	{:else if trail.review && trail.jobs.length}
		<p class="lead">
			<span class="run">{trailHeading(trail.review, now)}</span>
			<span class="sum">{trailSummary(trail)}</span>
		</p>
		<ol class="jobs">
			{#each trail.jobs as job, i (i)}
				{@const consult = job.consult}
				{@const keeper = job.actor === 'keeper'}
				<li class={['job', { keeper }]}>
					<span class="who" aria-hidden="true">{actorName(job.actor)}</span>
					<div class="what">
						<p class="title">{trailJobTitle(job, trail.claim)}</p>
						{#if consult?.statement}
							<blockquote>{consult.statement}</blockquote>
						{:else if keeper && reasoning}
							<blockquote>{reasoning}</blockquote>
						{/if}
						{#if consult?.cites.length}
							<ul class="cites" aria-label="What {job.actor} cited">
								{#each refsOf(consult.cites) as ref (ref.uid)}
									<li title={ref.uid}><NodeChip type={nodeType(ref.label)} label={short(ref.title)} href={ref.url ?? undefined} /></li>
								{/each}
							</ul>
						{/if}
						{#if job.steps.length}
							<details>
								<summary>{job.steps.length} graph {job.steps.length === 1 ? 'read' : 'reads'}</summary>
								<ol class="steps">
									{#each job.steps as step (step.n)}
										<li>
											<span class="line"><RefText runs={stepLineRuns(step, urlOf)} /></span>
											<span class="sub"
												><code>{step.tool}</code>{#if step.error}<span class="error">&nbsp;· {step.error}</span
													>{:else if step.count !== null}<span>&nbsp;· {step.count} {step.count === 1 ? 'row' : 'rows'}</span>{/if}</span
											>
										</li>
									{/each}
								</ol>
							</details>
						{/if}
					</div>
				</li>
			{/each}
		</ol>
	{:else if lines.length}
		<ol class="log">
			{#each lines as entry (entry.uid)}
				{@const why = logWhy(entry)}
				<li>
					<span class="at">{logTime(entry.at, now)}</span>
					<span><span class="said">{logSentence(entry)}</span>{#if why}<span class="sub">{why}</span>{/if}</span>
				</li>
			{/each}
		</ol>
	{:else}
		<p class="none">The Keeper's ledger has no record of how this claim was made.</p>
	{/if}
</section>

<style>
	h3 {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.none {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.lead {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		align-items: baseline;
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
	}
	.run {
		font-weight: var(--weight-semibold);
	}
	.sum {
		color: var(--color-text-muted);
	}
	.jobs,
	.steps,
	.cites,
	.log {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.job {
		position: relative;
		display: grid;
		grid-template-columns: 4.5rem minmax(0, 1fr);
		gap: var(--space-3);
		padding-bottom: var(--space-4);
	}
	/* The thread that ties the jobs into one run. */
	.job:not(:last-child)::before {
		content: '';
		position: absolute;
		top: var(--space-6);
		bottom: 0;
		left: 2.25rem;
		border-left: var(--border-hair) solid var(--color-line);
	}
	.who {
		position: relative;
		align-self: start;
		justify-self: center;
		padding: 0.125rem var(--space-2);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
	}
	.keeper .who {
		border-color: var(--color-accent);
		background: var(--color-accent-soft);
	}
	.what {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}
	.title {
		margin: 0;
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
	}
	blockquote {
		margin: 0;
		padding-left: var(--space-3);
		border-left: var(--border-focus) solid var(--color-line);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
	}
	.keeper blockquote {
		border-left-color: var(--color-accent);
	}
	.cites {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.cites li {
		max-width: 100%;
	}
	details summary {
		width: fit-content;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	details summary:hover {
		color: var(--color-text);
	}
	details summary:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: var(--border-focus);
		border-radius: var(--radius-sm);
	}
	.steps {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.steps li,
	.log li > span:last-child {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.line {
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
	}
	.sub {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.sub code {
		font-family: var(--font-mono);
	}
	.error {
		color: var(--color-danger);
	}
	.log li {
		display: grid;
		grid-template-columns: 3.5rem minmax(0, 1fr);
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-top: var(--border-hair) solid var(--color-line);
		font-size: var(--text-sm);
	}
	.at {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}
	@media (prefers-reduced-motion: no-preference) {
		details summary {
			transition: color var(--duration-fast) var(--ease-out);
		}
	}
</style>
