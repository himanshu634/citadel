<!--
@component
The review page (design direction D, "list and detail"): every Keeper claim waiting for a lead.
The list on the left holds them all; the open one fills the right with its statement, why it needs
a lead, the gap it answers, how the Keeper got there (`KeeperTrail`, read per claim) and its
evidence, and Reject or Approve under it. The open claim is in
the URL (`?claim=<uid>`), so a claim has a link. Decided claims stay in the list under "Decided
here" for the rest of the visit.

Why a page: the sidebar's "Review claims" item (with the count of claims waiting) opens it from
anywhere in the company, and the Systems rail stays for the agents' runs and the Keeper's log.
-->
<script lang="ts">
	import { CloudOff, LoaderCircle } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Badge, Banner, Button, ClaimApproval, EmptyState, Input, KeeperLog, KeeperTrail } from '$lib';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import {
		CLAIM_KINDS,
		decidedLine,
		decidedTag,
		decisionError,
		evidenceRefs,
		type DecisionError
	} from '$lib/keeper';
	import { buildingTitle, viewOf } from '$lib/overview';
	import { getPendingClaims } from '$lib/pendingClaims.svelte';
	import type { Claim, ClaimTrail, Gap, GraphView, LogEntry } from '$lib/types';
	import { shortUid } from '$lib/walk';

	let { data } = $props();
	const companies = getCompanies();
	const pendingCount = getPendingClaims();

	const company = $derived(companies.byslug(data.slug));
	const status = $derived(company ? viewOf(company) : null);
	const fetchable = $derived(status?.kind === 'data');
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));
	const systemsPath = $derived(resolve('/c/[slug]/systems', { slug: data.slug }));

	// The claims waiting and the gaps they answer, read together; again after each decision.
	type Ledger = { slug: string; claims: Claim[] | null; gaps: Gap[] | null; error: string | null };
	let ledger = $state.raw<Ledger | null>(null);
	let readNow = $state(0);
	const mine = $derived(ledger?.slug === data.slug ? ledger : null);
	const pending = $derived(mine?.claims ?? null);
	const gapText = $derived(new Map((mine?.gaps ?? []).map((g) => [g.uid, g.text])));

	$effect(() => {
		const slug = data.slug;
		void readNow;
		if (!fetchable) return;
		let live = true;
		void Promise.allSettled([api.keeper.claims(slug, 'pending_approval'), api.keeper.gaps(slug)]).then(
			([claims, gaps]) => {
				if (!live) return;
				const before = ledger?.slug === slug ? ledger : null;
				ledger = {
					slug,
					claims: claims.status === 'fulfilled' ? claims.value : (before?.claims ?? null),
					gaps: gaps.status === 'fulfilled' ? gaps.value : (before?.gaps ?? null),
					error: claims.status === 'rejected' ? describeError(claims.reason) : null
				};
				if (claims.status === 'fulfilled') pendingCount.put(slug, claims.value);
			}
		);
		return () => {
			live = false;
		};
	});

	// The graph names evidence and links it; until it arrives (or if it can't), chips show short uids.
	let loaded = $state.raw<GraphView | null>(null);
	const graph = $derived(loaded?.slug === data.slug ? loaded : null);
	$effect(() => {
		const slug = data.slug;
		if (!fetchable) return;
		let live = true;
		api.graph(slug).then(
			(view) => {
				if (live) loaded = view;
			},
			() => {}
		);
		return () => {
			live = false;
		};
	});
	const known = $derived(new Map((graph?.nodes ?? []).map((n) => [n.uid, n])));
	const refsOf = (uids: string[]) =>
		evidenceRefs(uids, (uid) => {
			const n = known.get(uid);
			return n ? { label: n.label, title: n.title, url: n.url } : null;
		});

	// The decisions lately logged, for the page with nothing waiting.
	let log = $state.raw<{ slug: string; entries: LogEntry[] } | null>(null);
	const recent = $derived(
		log?.slug === data.slug
			? log.entries.filter((e) => e.action === 'claim_approved' || e.action === 'claim_rejected').slice(0, 8)
			: null
	);
	$effect(() => {
		const slug = data.slug;
		void readNow;
		if (!fetchable || pending === null || pending.length) return;
		let live = true;
		api.keeper.log(slug, 100).then(
			(entries) => {
				if (live) log = { slug, entries };
			},
			() => {}
		);
		return () => {
			live = false;
		};
	});

	// The open claim: the one in the URL while it waits, else the first.
	const wanted = $derived(page.url.searchParams.get('claim'));
	const open = $derived(pending ? (pending.find((c) => c.uid === wanted) ?? pending[0] ?? null) : null);
	function select(uid: string | null) {
		const url = new URL(page.url);
		if (uid) url.searchParams.set('claim', uid);
		else url.searchParams.delete('claim');
		void goto(url, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// How the Keeper got to the open claim: read when it opens. Stays null while it loads.
	type Work = { uid: string; trail: ClaimTrail | null; error: string | null };
	let work = $state.raw<Work | null>(null);
	const openWork = $derived(open && work?.uid === open.uid ? work : null);
	$effect(() => {
		const slug = data.slug;
		const uid = open?.uid;
		if (!uid) return;
		let live = true;
		api.keeper.trail(slug, uid).then(
			(trail) => {
				if (live) work = { uid, trail, error: null };
			},
			(e) => {
				if (live) work = { uid, trail: null, error: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});
	const urlOf = (uid: string) => known.get(uid)?.url ?? null;

	// Decisions made on this visit, newest first.
	type Done = { claim: Claim; decision: 'approve' | 'reject'; by: string };
	let decided = $state<{ slug: string; items: Done[] }>({ slug: '', items: [] });
	const done = $derived(decided.slug === data.slug ? decided.items : []);
	const decidedHere = $derived(new Set(done.map((d) => d.claim.uid)));
	const lostLink = $derived(
		wanted && pending && !pending.some((c) => c.uid === wanted) && !decidedHere.has(wanted) ? wanted : null
	);
	let said = $state<{ slug: string; text: string; failed?: boolean } | null>(null);
	const saidLine = $derived(said?.slug === data.slug ? said : null);

	// The approver's name, typed once and kept in this browser (shared with every claim).
	const NAME_KEY = 'citadel-keeper-name';
	let approver = $state(readName());
	let nameError = $state<string | null>(null);
	let nameField = $state<HTMLElement | null>(null);
	function readName(): string {
		try {
			return localStorage.getItem(NAME_KEY) ?? '';
		} catch {
			return '';
		}
	}
	function onNameError(message: string) {
		nameError = message;
		nameField?.querySelector('input')?.focus();
	}

	async function decide(claim: Claim, decision: 'approve' | 'reject', by: string, why: string): Promise<DecisionError | null> {
		const slug = data.slug;
		let result: Claim;
		try {
			result = await api.keeper[decision](slug, claim.uid, { by, why });
		} catch (e) {
			const err = decisionError(e);
			if (err.gone) {
				said = { slug, text: err.message, failed: true };
				readNow++;
				void pendingCount.refresh(slug);
			}
			return err;
		}
		try {
			localStorage.setItem(NAME_KEY, by);
		} catch {
			// Private window or blocked storage: the name is typed again next time.
		}
		const list = pending ?? [];
		const at = list.findIndex((c) => c.uid === claim.uid);
		const rest = list.filter((c) => c.uid !== claim.uid);
		const next = rest[Math.min(Math.max(at, 0), rest.length - 1)] ?? null;
		decided = { slug, items: [{ claim: result, decision, by }, ...done] };
		said = { slug, text: decidedLine(decision, by, result) };
		if (mine) {
			ledger = { ...mine, claims: rest };
			pendingCount.put(slug, rest);
		}
		select(next?.uid ?? null);
		readNow++;
		return null;
	}
</script>

<svelte:head><title>Review claims · {company?.name ?? 'Review'} | Citadel</title></svelte:head>

{#if company && status}
	<div class="review-page">
		<header class="bar">
			<div class="title">
				<h1>Review claims</h1>
				<p class="lede">What the Keeper wants to write into {company.name}'s brain, waiting for a lead to say yes or no.</p>
			</div>
			{#if fetchable}
				<div class="controls">
					{#if pending}
						<p class="count" role="status">
							{pending.length} waiting{#if done.length}&nbsp;· {done.length} decided here{/if}
						</p>
					{/if}
					<div class="name" bind:this={nameField}>
						<Input
							label="Deciding as"
							placeholder="Your name"
							autocomplete="name"
							bind:value={approver}
							oninput={() => (nameError = null)}
							error={nameError ?? undefined}
						/>
					</div>
				</div>
			{/if}
		</header>

		{#if status.kind === 'invalid'}
			<div class="pad"><Banner tone="danger" title="Config invalid">{status.error}</Banner></div>
		{:else if status.kind === 'unreachable'}
			<div class="pad">
				<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
					Citadel can't reach FalkorDB, so the Keeper's claims can't be read. Start it with <code>make up</code>.
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
					title="Claims appear once the first build finishes"
					description="The Keeper reviews what {company.name}'s brain could not answer; what it wants to write waits here for a lead."
				/>
			</div>
		{:else if !mine}
			<p class="reading" role="status" aria-busy="true"><LoaderCircle class="spin" aria-hidden="true" />Reading the Keeper's claims</p>
		{:else if pending === null}
			<div class="pad">
				<EmptyState title="Can't read the Keeper's claims" description={mine.error ?? 'The API did not answer.'}>
					{#snippet action()}<Button onclick={() => readNow++}>Try again</Button>{/snippet}
				</EmptyState>
			</div>
		{:else if !pending.length && !done.length}
			<div class="pad empty">
				<EmptyState
					title="Nothing waits for you"
					description="When the Keeper writes a claim only a lead may approve, it shows here, and its count shows in the sidebar."
				>
					{#snippet action()}<Button href={systemsPath}>See the Keeper's work</Button>{/snippet}
				</EmptyState>
				{#if lostLink}<p class="note" role="status">The claim in the link no longer waits for a lead.</p>{/if}
				{#if recent?.length}
					<section class="recent" aria-labelledby="recent-h">
						<h2 id="recent-h">Recent decisions</h2>
						<KeeperLog entries={recent} gapText={(uid) => gapText.get(uid) ?? null} />
					</section>
				{/if}
			</div>
		{:else}
			<div class="body">
				<nav class="list" aria-label="Claims">
					{#if mine.error}<p class="note">Can't read all of the claims: {mine.error}</p>{/if}
					<h2>Waiting · {pending.length}</h2>
					{#if pending.length}
						<ul>
							{#each pending as claim (claim.uid)}
								{@const on = claim.uid === open?.uid}
								<li>
									<button type="button" class={['item', { on }]} aria-current={on ? 'true' : undefined} onclick={() => select(claim.uid)}>
										<span class="meta"><span class="kind">{CLAIM_KINDS[claim.kind] ?? claim.kind}</span>{shortUid(claim.subject)}</span>
										<span class="text">{claim.statement}</span>
									</button>
								</li>
							{/each}
						</ul>
					{:else}
						<p class="note">All decided. Nothing else waits for you.</p>
					{/if}
					{#if done.length}
						<h2 class="decided-h">Decided here · {done.length}</h2>
						<ul>
							{#each done as d (d.claim.uid)}
								{@const tag = decidedTag(d.decision, d.claim.status)}
								<li class="done">
									<span class="meta"><Badge tone={tag.tone}>{tag.text}</Badge>{shortUid(d.claim.subject)} · by {d.by}</span>
									<span class="text">{d.claim.statement}</span>
								</li>
							{/each}
						</ul>
					{/if}
				</nav>
				<section class="detail" aria-label="The open claim">
					{#if saidLine}
						<p class={['said', { failed: saidLine.failed }]} role="status">{saidLine.text}</p>
					{:else if lostLink}
						<p class="said failed" role="status">The claim in the link no longer waits for a lead; here is the first one that does.</p>
					{/if}
					{#if open}
						{#key open.uid}
							<ClaimApproval
								claim={open}
								gapText={open.gap ? (gapText.get(open.gap) ?? null) : null}
								evidence={refsOf(open.evidence)}
								subject={refsOf([open.subject])[0]}
								name={approver}
								onnameerror={onNameError}
								ondecide={(decision, by, why) => decide(open, decision, by, why)}
							>
								{#snippet work()}
									<KeeperTrail trail={openWork?.trail ?? null} failed={openWork?.error ?? null} {refsOf} {urlOf} />
								{/snippet}
							</ClaimApproval>
						{/key}
					{:else}
						<div class="pad">
							<EmptyState title="Nothing else waits for you" description="Every claim on this visit is decided. The Keeper's log on the Systems page has the full story.">
								{#snippet action()}<Button href={systemsPath}>Open Systems</Button>{/snippet}
							</EmptyState>
						</div>
					{/if}
				</section>
			</div>
		{/if}
	</div>
{/if}

<style>
	.review-page {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
		align-items: flex-end;
		justify-content: space-between;
		padding: var(--space-5) var(--space-8);
		border-bottom: var(--border-hair) solid var(--color-line);
		background: var(--color-surface);
	}
	h1 {
		margin: 0;
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.lede {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-5);
		align-items: flex-end;
	}
	.count {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.name {
		width: 14rem;
	}
	.pad {
		padding: var(--space-6) var(--space-8);
	}
	.empty {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		max-width: 48rem;
	}
	.recent h2,
	.list h2 {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.reading {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		padding: var(--space-6) var(--space-8);
		color: var(--color-text-muted);
	}
	.reading :global(.spin) {
		width: 1rem;
		height: 1rem;
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.reading :global(.spin) {
			animation: none;
		}
	}
	.body {
		display: grid;
		grid-template-columns: 24rem minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.list {
		min-height: 0;
		overflow: auto;
		padding: var(--space-4) 0;
		background: var(--color-surface);
		border-right: var(--border-hair) solid var(--color-line);
	}
	.list h2 {
		padding-inline: var(--space-5);
	}
	.list h2.decided-h {
		margin-top: var(--space-6);
	}
	.list ul {
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: var(--border-hair) solid var(--color-line);
	}
	.item,
	.done {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		width: 100%;
		padding: var(--space-3) var(--space-5);
		border: 0;
		border-bottom: var(--border-hair) solid var(--color-line);
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
	}
	.item {
		cursor: pointer;
		transition: background-color var(--duration-fast) var(--ease-out);
	}
	.item:hover {
		background: var(--color-surface-sunken);
	}
	.item:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: calc(-1 * var(--border-focus));
	}
	.item.on {
		background: var(--color-accent-soft);
		box-shadow: inset var(--space-1) 0 0 var(--color-accent);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.kind {
		padding: 0 var(--space-1);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
	}
	.text {
		display: -webkit-box;
		overflow: hidden;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		font-size: var(--text-md);
		line-height: var(--leading-ui);
	}
	.done .text {
		color: var(--color-text-muted);
	}
	.note {
		margin: 0;
		padding: var(--space-2) var(--space-5);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.empty .note {
		padding: 0;
	}
	.detail {
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--color-surface-raised);
	}
	.said {
		flex: none;
		margin: 0;
		padding: var(--space-3) var(--space-10);
		border-bottom: var(--border-hair) solid var(--color-line);
		background: var(--color-success-soft);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.said.failed {
		background: var(--color-warning-soft);
	}
	@media (max-width: 64rem) {
		.body {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: minmax(0, 35%) minmax(0, 1fr);
		}
		.list {
			border-right: 0;
			border-bottom: var(--border-hair) solid var(--color-line);
		}
		.bar,
		.pad,
		.said {
			padding-inline: var(--space-4);
		}
	}
</style>
