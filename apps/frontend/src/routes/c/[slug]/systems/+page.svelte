<!--
@component
The Systems page (design direction A, "the map with the agent's trail"): the company map from the
Graph page, with the agents' latest run drawn over it. Each step sits on the node it was about,
numbered in order and joined by an ink line; while the run is going, the node the agent is on
has an ink ring and says what it is doing. The rail lists the run's steps and the earlier runs.

Why this shape: it answers "where is the agent working, and what has it done on the graph" in
one look, on the map people already know. Runs come from GET .../activity (Ask turns and Keeper
reviews), read again every few seconds while one is going and less often when not.
The map is laid out once per graph; only the trail moves.

The Keeper's controls live here too (design direction A2): Review now in the bar, and in the rail
the claims waiting for a lead (Approve or Reject with a typed name) and the Keeper's log. They are
read again when a Keeper run starts or ends, after Review now and after each decision.
-->
<script lang="ts">
	import { CloudOff, LoaderCircle } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { AgentRun, Banner, Button, ClaimApproval, EmptyState, KeeperLog, TerritoryMap } from '$lib';
	import { actorName, featured, hereLabel, shownRun, trailOf, type Pick } from '$lib/activity';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import type { MapLayout } from '$lib/graph';
	import { cachedLayout, computeLayout } from '$lib/graphLayout';
	import {
		decidedLine,
		decisionError,
		evidenceRefs,
		keeperRunning,
		keeperRunsKey,
		railLog,
		reviewNote,
		type DecisionError
	} from '$lib/keeper';
	import { buildingTitle, viewOf } from '$lib/overview';
	import { ago } from '$lib/time';
	import type { Activity, Claim, Gap, GraphView, LogEntry } from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const status = $derived(company ? viewOf(company) : null);
	const fetchable = $derived(status?.kind === 'data');
	const syncedAt = $derived(company?.last_synced_at ?? null);
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));
	const askPath = $derived(resolve('/c/[slug]/ask', { slug: data.slug }));

	// The map: the Graph page's view and layout (shared cache), fetched once per build.
	let attempt = $state(0);
	let loaded = $state.raw<GraphView | null>(null);
	let placed = $state.raw<{ view: GraphView; layout: MapLayout } | null>(null);
	let problem = $state<{ slug: string; message: string } | null>(null);
	const graph = $derived(loaded?.slug === data.slug ? loaded : null);
	const layout = $derived(placed && placed.view === graph ? placed.layout : null);
	const error = $derived(problem?.slug === data.slug ? problem.message : null);

	$effect(() => {
		const slug = data.slug;
		void attempt;
		void syncedAt;
		if (!fetchable) return;
		problem = null;
		let live = true;
		api.graph(slug).then(
			(answer) => {
				const mine = companies.guard(slug, answer);
				if (!live || !mine) return;
				loaded = mine;
				const hit = cachedLayout(mine);
				if (hit) placed = { view: mine, layout: hit };
				else
					void computeLayout(mine).then((l) => {
						if (live) placed = { view: mine, layout: l };
					});
			},
			(e) => {
				if (live && slug === companies.current) problem = { slug, message: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});

	// The runs: read often while one is going, rarely while idle or in a hidden tab.
	const LIVE_MS = 1500;
	const IDLE_MS = 6000;
	const HIDDEN_MS = 20000;
	let activity = $state.raw<{ slug: string; value: Activity } | null>(null);
	let activityError = $state<string | null>(null);
	const runs = $derived(activity?.slug === data.slug ? activity.value.runs : null);
	/** Bumped to read the runs now (after Review now or an approval) instead of at the next tick. */
	let readRunsNow = $state(0);

	$effect(() => {
		const slug = data.slug;
		void readRunsNow;
		if (!fetchable) return;
		let live = true;
		let timer: ReturnType<typeof setTimeout> | undefined;
		async function tick() {
			let running = false;
			try {
				const value = await api.activity(slug);
				if (!live) return;
				activity = { slug, value };
				activityError = null;
				running = value.running;
			} catch (e) {
				if (!live) return;
				activityError = describeError(e);
			}
			timer = setTimeout(tick, document.hidden ? HIDDEN_MS : running ? LIVE_MS : IDLE_MS);
		}
		void tick();
		return () => {
			live = false;
			clearTimeout(timer);
		};
	});

	// The run on the map: the one picked in the rail, else one that is going, else the newest.
	// A pick holds while the run it was picked over is still the featured one (see `shownRun`).
	const working = $derived(runs?.find((r) => r.status === 'running') ?? null);
	let picked = $state<Pick | null>(null);
	const run = $derived(runs ? shownRun(runs, picked) : null);
	function pick(id: string) {
		picked = { id, featuredAt: featured(runs ?? [])?.id ?? null };
	}
	const territoryOf = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n.territory])));
	const urls = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n.url])));
	const trail = $derived(run && graph ? trailOf(run, (uid) => territoryOf.get(uid) ?? null) : null);
	const here = $derived(run?.status === 'running' ? hereLabel(run) : null);
	const others = $derived((runs ?? []).filter((r) => r.id !== run?.id));
	const chatHref = (threadId: string | null) =>
		threadId ? `${askPath}?${new URLSearchParams({ thread: threadId })}` : null;

	// The Keeper: its pending claims, its gaps (for their text) and its log, read together.
	type Ledger = { slug: string; claims: Claim[] | null; gaps: Gap[] | null; log: LogEntry[] | null; error: string | null };
	let ledger = $state.raw<Ledger | null>(null);
	let readLedgerNow = $state(0);
	const keeperKey = $derived(keeperRunsKey(runs ?? []));
	/** Lines read for the log: enough that 20 remain once the episode lines are left out. */
	const LOG_READ = 60;
	const LOG_SHOWN = 20;
	const mine = $derived(ledger?.slug === data.slug ? ledger : null);
	const pending = $derived(mine?.claims ?? null);
	const gapText = $derived(new Map((mine?.gaps ?? []).map((g) => [g.uid, g.text])));
	const pendingIds = $derived(new Set((pending ?? []).map((c) => c.uid)));

	$effect(() => {
		const slug = data.slug;
		void keeperKey;
		void readLedgerNow;
		if (!fetchable) return;
		let live = true;
		void Promise.allSettled([
			api.keeper.claims(slug, 'pending_approval'),
			api.keeper.gaps(slug),
			api.keeper.log(slug, LOG_READ)
		]).then(([claims, gaps, log]) => {
			if (!live) return;
			const failed = [claims, gaps, log].find((r) => r.status === 'rejected');
			const before = ledger?.slug === slug ? ledger : null;
			ledger = {
				slug,
				claims: claims.status === 'fulfilled' ? claims.value : (before?.claims ?? null),
				gaps: gaps.status === 'fulfilled' ? gaps.value : (before?.gaps ?? null),
				log: log.status === 'fulfilled' ? railLog(log.value, LOG_SHOWN) : (before?.log ?? null),
				error: failed ? describeError(failed.reason) : null
			};
		});
		return () => {
			live = false;
		};
	});

	// Review now: disabled while a Keeper review runs. A review that ends at once (skipped without a
	// Claude key) never reaches the runs, so its answer is said here.
	let starting = $state(false);
	let reviewSaid = $state<{ slug: string; text: string; failed: boolean } | null>(null);
	const reviewing = $derived(starting || keeperRunning(runs ?? []));
	const reviewLine = $derived(reviewSaid?.slug === data.slug ? reviewSaid : null);
	async function reviewNow() {
		const slug = data.slug;
		starting = true;
		reviewSaid = null;
		try {
			const review = await api.keeper.review(slug);
			const text = reviewNote(review);
			if (text) reviewSaid = { slug, text, failed: review.state === 'failed' };
		} catch (e) {
			reviewSaid = { slug, text: `Review now did not start: ${describeError(e)}`, failed: true };
		} finally {
			starting = false;
			readRunsNow++;
			readLedgerNow++;
		}
	}

	// A lead's decision. The typed name is kept in this browser, so it is typed once.
	const NAME_KEY = 'citadel-keeper-name';
	let approver = $state(readName());
	let decided = $state<{ slug: string; text: string } | null>(null);
	const decidedNote = $derived(decided?.slug === data.slug ? decided.text : null);
	function readName(): string {
		try {
			return localStorage.getItem(NAME_KEY) ?? '';
		} catch {
			return '';
		}
	}
	async function decide(claim: Claim, decision: 'approve' | 'reject', by: string, why: string): Promise<DecisionError | null> {
		const slug = data.slug;
		let result: Claim;
		try {
			result = await api.keeper[decision](slug, claim.uid, { by, why });
		} catch (e) {
			const err = decisionError(e);
			if (err.gone) {
				decided = { slug, text: err.message };
				readLedgerNow++;
			}
			return err;
		}
		try {
			localStorage.setItem(NAME_KEY, by);
		} catch {
			// Private window or blocked storage: the name is typed again next time.
		}
		decided = { slug, text: decidedLine(decision, by, result) };
		readLedgerNow++;
		readRunsNow++;
		return null;
	}
	const known = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n])));
	const evidenceOf = (claim: Claim) =>
		evidenceRefs(claim.evidence, (uid) => {
			const n = known.get(uid);
			return n ? { label: n.label, title: n.title, url: n.url } : null;
		});
	const claimHref = (uid: string) => (pendingIds.has(uid) ? `#keeper-${uid}` : null);

	const statusLine = $derived(
		working
			? `${actorName(working.actor)} is working now`
			: runs?.length
				? `No agent is working now. The last run started ${ago(runs[0].started_at)}.`
				: runs
					? 'No agent has worked on this graph yet.'
					: ''
	);
</script>

<svelte:head><title>Systems · {company?.name ?? 'Systems'} | Citadel</title></svelte:head>

{#if company && status}
	<div class="systems-page">
		<header class="bar">
			<div class="title">
				<h1>Systems</h1>
				<p class="lede">Where the agents are working, and every step they took on the graph.</p>
			</div>
			<div class="controls">
				{#if statusLine}
					<p class={['state', { live: working }]} role="status">
						{#if working}<span class="ring" aria-hidden="true"></span>{/if}{statusLine}
					</p>
				{/if}
				{#if fetchable}
					<Button variant="primary" loading={starting} disabled={reviewing} onclick={reviewNow}>
						{reviewing && !starting ? 'Keeper reviewing' : 'Review now'}
					</Button>
				{/if}
			</div>
			{#if reviewLine}
				<p class={['said', { failed: reviewLine.failed }]} role="status">{reviewLine.text}</p>
			{/if}
		</header>

		{#if status.kind === 'invalid'}
			<div class="pad"><Banner tone="danger" title="Config invalid">{status.error}</Banner></div>
		{:else if status.kind === 'unreachable'}
			<div class="pad">
				<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
					Citadel can't reach FalkorDB, so the map can't be drawn. Start it with <code>make up</code>.
				</Banner>
			</div>
		{:else if status.kind === 'waiting'}
			<div class="pad">
				<Banner
					tone="warning"
					title={buildingTitle(company)}
					icon={company.status === 'building' ? LoaderCircle : undefined}
					spin={company.status === 'building'}
				>
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
				<EmptyState
					title="The map appears when the first build finishes"
					description="Once {company.name}'s graph is built, every step an agent takes on it is drawn here."
				/>
			</div>
		{:else if error}
			<div class="pad">
				<EmptyState title="Can't read {company.name}'s graph" description={error}>
					{#snippet action()}<Button onclick={() => attempt++}>Try again</Button>{/snippet}
				</EmptyState>
			</div>
		{:else if !graph || !layout}
			<div class="drawing" role="status" aria-busy="true">
				<LoaderCircle class="spin" aria-hidden="true" />
				{graph ? 'Drawing the map' : 'Reading the graph'}
			</div>
		{:else}
			<div class="body">
				<div class="view">
					<TerritoryMap view={graph} {layout} {trail} {here} />
				</div>
				<aside class="side" aria-label="Agent runs and the Keeper">
					{#if decidedNote}<p class="note" role="status">{decidedNote}</p>{/if}
					{#if pending?.length}
						<section class="keeper" aria-labelledby="waiting-h">
							<h2 id="waiting-h">Waiting for you · {pending.length}</h2>
							{#each pending as claim (claim.uid)}
								<div id="keeper-{claim.uid}">
									<ClaimApproval
										{claim}
										gapText={claim.gap ? (gapText.get(claim.gap) ?? null) : null}
										evidence={evidenceOf(claim)}
										bind:name={approver}
										ondecide={(decision, by, why) => decide(claim, decision, by, why)}
									/>
								</div>
							{/each}
						</section>
					{/if}
					{#if activityError && !runs}
						<p class="note">Can't read the agents' runs: {activityError}</p>
					{:else if !runs}
						<p class="note">Reading the agents' runs</p>
					{:else if run && trail}
						<AgentRun {run} {trail} href={chatHref(run.thread_id)} urlOf={(uid) => urls.get(uid) ?? null} />
					{:else}
						<EmptyState
							title="No agent has walked this graph yet"
							description="Ask {company.name} a question, or press Review now: each step an agent takes shows here, on the map."
						>
							{#snippet action()}<Button href={askPath}>Ask a question</Button>{/snippet}
						</EmptyState>
					{/if}
					<section class="keeper" aria-labelledby="log-h">
						<h2 id="log-h">Keeper log</h2>
						{#if mine?.error}<p class="note">Can't read all of the Keeper's ledger: {mine.error}</p>{/if}
						{#if mine?.log}
							<KeeperLog entries={mine.log} gapText={(uid) => gapText.get(uid) ?? null} {claimHref} />
						{:else if !mine}
							<p class="note">Reading the Keeper's log</p>
						{/if}
					</section>
					{#if runs && run}
						{#if others.length}
							<div class="earlier">
								<h2>Other runs</h2>
								<ul>
									{#each others as r (r.id)}
										<li>
											<button type="button" onclick={() => pick(r.id)}>
												<span class="q">{r.title}</span>
												<span class="when">
													{r.status === 'running' ? 'Working now' : ago(r.started_at)} · {r.steps.length}
													{r.steps.length === 1 ? 'step' : 'steps'}
												</span>
											</button>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{/if}
				</aside>
			</div>
		{/if}
	</div>
{/if}

<style>
	.systems-page {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3) var(--space-4);
		padding: var(--space-3) var(--space-5);
		background: var(--color-surface);
		border-bottom: var(--border-hair) solid var(--color-line);
	}
	.title {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	h1 {
		margin: 0;
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: var(--leading-tight);
	}
	.lede {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.said {
		flex-basis: 100%;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.said.failed {
		color: var(--color-danger);
	}
	.keeper {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.state {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.state.live {
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-full);
		background: var(--color-text);
		color: var(--color-surface);
		font-weight: var(--weight-semibold);
	}
	.ring {
		width: var(--space-2);
		height: var(--space-2);
		border: var(--border-focus) solid var(--color-surface);
		border-radius: var(--radius-full);
	}
	.pad {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.drawing {
		display: flex;
		flex: 1;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
	}
	.drawing :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.drawing :global(.spin) {
			animation: none;
		}
	}
	.body {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 22rem;
		grid-template-rows: minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.view {
		min-height: 0;
		overflow: hidden;
	}
	.side {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-height: 0;
		overflow: auto;
		padding: var(--space-5);
		background: var(--color-surface);
		border-left: var(--border-hair) solid var(--color-line);
	}
	.note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.earlier h2,
	.keeper h2 {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.keeper h2 {
		margin: 0;
	}
	.earlier ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.earlier button {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		width: 100%;
		padding: var(--space-2) 0;
		border: 0;
		border-top: var(--border-hair) solid var(--color-line);
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.earlier button:hover .q {
		text-decoration: underline;
	}
	.earlier button:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: var(--border-focus);
	}
	.q {
		font-size: var(--text-md);
	}
	.when {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	@media (max-width: 64rem) {
		.body {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: minmax(0, 1fr) minmax(0, 45%);
		}
		.side {
			border-left: 0;
			border-top: var(--border-hair) solid var(--color-line);
		}
	}
</style>
