<script lang="ts">
	import { ArrowUpRight, Network, RefreshCw } from '@lucide/svelte';
	import {
		ActivityBars,
		Button,
		Card,
		CitedAnswer,
		EntityRow,
		Stat,
		Tabs,
		Tooltip,
		WorkItemRow
	} from '$lib';
	import {
		company,
		featuredAnswer,
		graphCounts,
		people,
		recentWork,
		suggestedQuestions,
		systemActivity
	} from '$lib/data/sample';
	import { NODE_PLURALS } from '$lib/types';

	let workFilter = $state('all');
	const openCount = $derived(recentWork.filter((w) => w.state === 'open').length);
	const tabItems = $derived([
		{ value: 'all', label: 'All', count: recentWork.length },
		{ value: 'open', label: 'Open', count: openCount },
		{ value: 'merged', label: 'Merged', count: recentWork.length - openCount }
	]);
	const since = new Date(company.since).toLocaleDateString('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric'
	});
</script>

<svelte:head><title>Overview, {company.name} | Citadel</title></svelte:head>

<div class="page">
	<header class="page-head">
		<div>
			<h1>{company.name}</h1>
			<p>Engineering activity since {since}, in graph <code>brain_{company.slug}</code>.</p>
		</div>
		<div class="head-actions">
			<Tooltip text="Pull new activity from every source">
				{#snippet trigger(props)}
					<Button {...props}><RefreshCw aria-hidden="true" />Sync now</Button>
				{/snippet}
			</Tooltip>
			<Button variant="primary"><Network aria-hidden="true" />Open graph</Button>
		</div>
	</header>

	<section aria-labelledby="graph-heading" class="summary">
		<h2 id="graph-heading" class="sr-only">Graph contents</h2>
		<dl class="stats">
			{#each graphCounts as g (g.type)}
				<Stat type={g.type} label={NODE_PLURALS[g.type]} value={g.count} />
			{/each}
		</dl>
	</section>

	<div class="grid">
		<Card title="Latest answer" description="Asked today by an agent on the identity team" class="answer-card">
			{#snippet actions()}
				<Button variant="ghost" size="sm">See all answers</Button>
			{/snippet}
			<CitedAnswer answer={featuredAnswer}>
				{#snippet actions()}
					<Button size="sm"><Network aria-hidden="true" />Show in graph</Button>
				{/snippet}
			</CitedAnswer>
		</Card>

		<Card title="Try asking" description="Questions this graph can answer with sources">
			<ul class="suggestions">
				{#each suggestedQuestions as q (q)}
					<li>
						<button type="button" class="suggestion">
							<span>{q}</span>
							<ArrowUpRight aria-hidden="true" />
						</button>
					</li>
				{/each}
			</ul>
		</Card>

		<Card title="Recent work" description="Pull requests, issues and threads" class="work-card">
			<Tabs items={tabItems} bind:value={workFilter} label="Filter work items">
				{#snippet panel(filter)}
					{@const list =
						filter === 'all'
							? recentWork
							: recentWork.filter((w) =>
									filter === 'open' ? w.state === 'open' : w.state !== 'open'
								)}
					<ul class="list">
						{#each list as item (item.uid)}
							<li><WorkItemRow {item} /></li>
						{/each}
					</ul>
				{/snippet}
			</Tabs>
		</Card>

		<Card title="Changes by system" description="Commits touching each system since {since}">
			<ActivityBars
				unit="changes"
				items={systemActivity.map((s) => ({ label: s.name, value: s.changes, meta: s.team }))}
			/>
		</Card>

		<Card title="People" description="Authors and reviewers in this graph">
			<ul class="list people">
				{#each people as p, i (p.login)}
					<li>
						<EntityRow
							name={p.name}
							type="person"
							meta="{p.team}, {p.prs} PRs, {p.reviews} reviews"
							selected={i === 0}
						/>
					</li>
				{/each}
			</ul>
		</Card>
	</div>
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.page-head {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: var(--space-4);
	}
	h1 {
		font-size: var(--text-2xl);
		font-variation-settings: 'wdth' var(--width-brand);
		font-weight: var(--weight-black);
	}
	.page-head p {
		margin-top: var(--space-1);
		color: var(--color-text-muted);
	}
	.head-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.summary {
		padding: var(--space-5);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
		gap: var(--space-5);
		margin: 0;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(12, minmax(0, 1fr));
		grid-auto-flow: row dense;
		gap: var(--space-4);
		align-items: start;
	}
	.grid > :global(*) {
		grid-column: span 4;
	}
	.grid > :global(.answer-card) {
		grid-column: span 8;
		grid-row: span 2;
	}
	.grid > :global(.work-card) {
		grid-column: span 8;
	}
	.grid > :global(:last-child) {
		grid-column: span 4;
	}
	@media (max-width: 1100px) {
		.grid > :global(*),
		.grid > :global(.answer-card),
		.grid > :global(.work-card),
		.grid > :global(:last-child) {
			grid-column: span 6;
			grid-row: auto;
		}
		.grid > :global(.answer-card),
		.grid > :global(.work-card) {
			grid-column: 1 / -1;
		}
	}
	@media (max-width: 720px) {
		.grid > :global(*),
		.grid > :global(:last-child) {
			grid-column: 1 / -1;
		}
	}
	.list {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.list > li + li {
		border-top: var(--border-hair) solid var(--color-line);
	}
	.people > li + li {
		border-top: 0;
	}
	.suggestions {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.suggestion {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		width: 100%;
		min-height: var(--control-lg);
		padding: var(--space-2) var(--space-3);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		text-align: left;
		cursor: pointer;
	}
	.suggestion:hover {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}
	.suggestion :global(svg) {
		width: 1rem;
		height: 1rem;
		flex: none;
		color: var(--color-text-muted);
	}
</style>
