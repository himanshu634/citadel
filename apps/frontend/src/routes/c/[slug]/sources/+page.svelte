<!--
@component
The Sources page (design direction A, the source ledger): where a company's graph comes from. One
row per source in the company file (`SourceRow`), a row for the nodes made from links, and the
sync records whose source has left the file. A banner says when a source stops every sync or loads
nothing; each such row says why and links to Settings, which stays the place to edit sources.

Why the rules: the page only reads and syncs. Counts are per `source` label (`ledger()` in
`$lib/sources` decides which row shows which), because the graph cannot tell two folders of one
type apart. It works before the first build (the rows come from the file and the adapters'
checks), so only an invalid file or an unreachable graph stops it. A finished build refetches.
-->
<script lang="ts">
	import { CloudOff, LoaderCircle, Link2, RefreshCw, Trash2 } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { Badge, Banner, Button, Dialog, EmptyState, SourceRow } from '$lib';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import { buildingTitle, viewOf } from '$lib/overview';
	import { headline, kindLines, ledger, sourceTitle, summary, when } from '$lib/sources';
	import { startSync, type SyncOutcome } from '$lib/sync';
	import type { SourcesOut, SyncRecord } from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const view = $derived(company ? viewOf(company) : null);
	const readable = $derived(view !== null && view.kind !== 'invalid' && view.kind !== 'unreachable');
	const busy = $derived(company?.status === 'building');
	// Primitives, so a status event that changes nothing here does not refetch.
	const syncedAt = $derived(company?.last_synced_at ?? null);
	const companyStatus = $derived(company?.status ?? null);
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));
	const settingsPath = $derived(resolve(`/c/${data.slug}/settings` as `/c/${string}`));

	/** The last answer, whichever company it was for; only the current slug's is ever shown. */
	let loaded = $state<SourcesOut | null>(null);
	let problem = $state<{ slug: string; message: string } | null>(null);
	let attempt = $state(0);

	const out = $derived(loaded?.slug === data.slug ? loaded : null);
	const error = $derived(problem?.slug === data.slug ? problem.message : null);
	const loading = $derived(readable && !out && !error);

	$effect(() => {
		const slug = data.slug;
		void attempt;
		void syncedAt; // a finished sync or build refreshes the rows
		void companyStatus;
		if (!readable) return;
		problem = null;
		let live = true;
		api.sources(slug).then(
			(answer) => {
				if (live && slug === companies.current) loaded = answer;
			},
			(e) => {
				if (live && slug === companies.current) problem = { slug, message: describeError(e) };
			}
		);
		return () => {
			live = false;
		};
	});

	const book = $derived(out ? ledger(out.sources, out.labels) : null);
	const notice = $derived(out ? summary(out.sources) : null);
	const locations = $derived(new Map((out?.sources ?? []).map((s) => [s.key, s.location])));
	const derivedLines = $derived(book?.derived ? kindLines([book.derived]) : []);
	/** The newest sync of any source: links are remade on every one. */
	const latestRun = $derived(
		when(
			(out?.sources ?? [])
				.map((s) => s.last_run)
				.filter((t): t is string => t !== null)
				.sort()
				.at(-1) ?? null
		)
	);

	/** Rows opened by the person, by source key; one per company page. */
	let opened = $state<Record<string, boolean>>({});

	// Sync. `syncing` is the source key ('*' for all) and the slug it belongs to.
	let syncing = $state<{ slug: string; key: string } | null>(null);
	let syncFailed = $state<{
		slug: string;
		outcome: Exclude<SyncOutcome, { kind: 'started' }>;
	} | null>(null);
	const syncProblem = $derived(syncFailed?.slug === data.slug ? syncFailed.outcome : null);

	async function sync(key: string) {
		const slug = data.slug;
		if (syncing?.slug === slug) return; // set before the first await: one request per click
		syncing = { slug, key };
		syncFailed = null;
		const outcome = await startSync(slug, key === '*' ? undefined : [key]);
		if (outcome.kind !== 'started') syncFailed = { slug, outcome };
		await companies.load(); // the status flips to building, which disables the buttons
		if (syncing?.slug === slug) syncing = null;
	}
	const syncingKey = $derived(syncing?.slug === data.slug ? syncing.key : null);

	// Removing a leftover sync record, behind a confirm.
	let removing = $state<SyncRecord | null>(null);
	let removeOpen = $state(false);
	let removeBusy = $state(false);
	let removeError = $state<string | null>(null);

	function askRemove(record: SyncRecord) {
		removing = record;
		removeError = null;
		removeOpen = true;
	}

	async function confirmRemove() {
		if (!removing) return;
		removeBusy = true;
		removeError = null;
		try {
			await api.forgetLeftover(data.slug, removing.key);
			removeOpen = false;
			attempt++;
			void companies.load(); // the top bar's "Synced" time is the newest sync record
		} catch (e) {
			removeError = describeError(e);
		} finally {
			removeBusy = false;
		}
	}

	const fmt = (n: number) => n.toLocaleString('en-GB');
	/** The part of a sync key after its type: `canonical_jsonl:apps/x` -> `apps/x`. */
	const keyPlace = (key: string) => key.slice(key.indexOf(':') + 1);
	const keyType = (record: SyncRecord) => record.adapter ?? record.key.split(':')[0];
</script>

<svelte:head><title>Sources | {company?.name ?? 'Company'} | Citadel</title></svelte:head>

{#if company && view}
	<div class="page">
		<header class="page-head">
			<div>
				<h1>Sources</h1>
				<p>
					Where {company.name}'s brain reads from.
					{#if out}{headline(out.sources)}{/if}
				</p>
			</div>
			{#if readable}
				<div class="head-actions">
					<Button href={settingsPath}>Edit in Settings</Button>
					<Button
						onclick={() => sync('*')}
						loading={syncingKey === '*'}
						disabled={busy || (out?.sources.length ?? 0) === 0}
					>
						<RefreshCw aria-hidden="true" />Sync all
					</Button>
				</div>
			{/if}
		</header>

		{#if view.kind === 'invalid'}
			<Banner tone="danger" title="Config invalid">
				{view.error}
				{#snippet action()}<Button href={settingsPath}>Open Settings</Button>{/snippet}
			</Banner>
		{:else if view.kind === 'unreachable'}
			<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
				Citadel can't reach FalkorDB, so it can't say what each source loaded. Start it with
				<code>make up</code>.
			</Banner>
		{:else}
			{#if busy}
				<Banner tone="warning" title={buildingTitle(company)} icon={LoaderCircle} spin>
					Syncing waits until it ends; the rows update then.
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
			{:else if syncProblem?.kind === 'running'}
				<Banner tone="warning" title="A build is running">
					Wait for it to finish, or stop it from its progress page, then sync again.
					{#snippet action()}<Button href={buildPath}>See progress</Button>{/snippet}
				</Banner>
			{:else if syncProblem?.kind === 'failed'}
				<Banner tone="danger" title="Could not start the sync">{syncProblem.message}</Banner>
			{:else if view.kind === 'data' && view.failure}
				<Banner tone="danger" title="Last build failed">
					{view.failure}
					{#snippet action()}<Button href={buildPath}>See details</Button>{/snippet}
				</Banner>
			{/if}

			{#if error}
				<EmptyState title="Can't read {company.name}'s sources" description={error}>
					{#snippet action()}<Button onclick={() => attempt++}>Try again</Button>{/snippet}
				</EmptyState>
			{:else if loading || !out || !book}
				<div class="skeleton" role="status" aria-busy="true">
					<span class="sr-only">Loading sources</span>
					<div class="block"></div>
				</div>
			{:else if out.sources.length === 0}
				<EmptyState
					title="No sources yet"
					description="Add a GitHub repository, a documents folder or JSONL records in Settings, then sync."
				>
					{#snippet action()}<Button variant="primary" href={settingsPath}>Add a source</Button>{/snippet}
				</EmptyState>
			{:else}
				{#if notice}
					<Banner tone={notice.tone} title={notice.title}>{notice.body}</Banner>
				{/if}

				<div class="ledger">
					<table>
						<caption class="sr-only">Sources of {company.name}</caption>
						<thead>
							<tr>
								<th scope="col">Source</th>
								<th scope="col">Status</th>
								<th scope="col">Last sync</th>
								<th scope="col">Read up to</th>
								<th scope="col">In the graph</th>
								<th scope="col"><span class="sr-only">Actions</span></th>
							</tr>
						</thead>
						{#each out.sources as source (source.key)}
							<SourceRow
								{source}
								credit={book.credits.get(source.key)!}
								since={out.since}
								bind:open={() => opened[source.key] ?? false, (v) => (opened[source.key] = v)}
								settingsHref={settingsPath}
								onsync={() => sync(source.key)}
								syncing={syncingKey === source.key}
								{busy}
								{locations}
							/>
						{/each}
						{#if book.derived}
							<tbody class="derived">
								<tr>
									<th scope="row">
										<div class="name">
											<span class="icon"><Link2 aria-hidden="true" /></span>
											<span class="who">
												<span class="title">Made from links</span>
												<span class="sub">Authors, reviewers and file paths the sources mention</span>
											</span>
										</div>
									</th>
									<td><Badge>Every sync</Badge></td>
									<td>
										{#if latestRun}
											<span class="main tabular">{latestRun}</span>
											<span class="sub">Remade with every sync</span>
										{:else}
											<span class="muted">With every sync</span>
										{/if}
									</td>
									<td><span class="muted">Not dated</span></td>
									<td>
										<span class="main tabular">{fmt(book.derived.total)} nodes</span>
										<span class="sub">
											{derivedLines.map((l) => `${fmt(l.count)} ${l.name.toLowerCase()}`).join(', ')}
										</span>
									</td>
									<td></td>
								</tr>
							</tbody>
						{/if}
						{#each book.other as group (group.source)}
							<tbody class="derived">
								<tr>
									<th scope="row">
										<div class="name">
											<span class="icon"><Link2 aria-hidden="true" /></span>
											<span class="who">
												<span class="title">Other records</span>
												<span class="location">{group.source}</span>
											</span>
										</div>
									</th>
									<td><Badge>No source</Badge></td>
									<td><span class="muted">Unknown</span></td>
									<td><span class="muted">Not dated</span></td>
									<td><span class="main tabular">{fmt(group.total)} nodes</span></td>
									<td></td>
								</tr>
							</tbody>
						{/each}
					</table>
				</div>
				{#if !out.built}
					<p class="muted">Nothing is in the graph yet: the first sync loads every source above.</p>
				{/if}

				{#if out.leftovers.length > 0}
					<section class="leftovers" aria-labelledby="leftovers-title">
						<div>
							<h2 id="leftovers-title">No longer in the config</h2>
							<p class="muted">
								Sync records of sources that left the company file, or folders that moved. They
								load nothing now. Removing one keeps every node.
							</p>
						</div>
						<ul>
							{#each out.leftovers as record (record.key)}
								<li>
									<span class="who">
										<span class="title faded">{sourceTitle(keyType(record))}</span>
										<span class="location">{keyPlace(record.key)}</span>
									</span>
									<span class="sub">
										Last sync {when(record.last_run) ?? 'unknown'}{#if record.records !== null},
											{fmt(record.records)} records{/if}
									</span>
									<Button size="sm" variant="ghost" onclick={() => askRemove(record)} disabled={busy}>
										<Trash2 aria-hidden="true" />Remove
									</Button>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
			{/if}
		{/if}
	</div>

	<Dialog
		bind:open={() => removeOpen, (v) => (removeOpen = v || removeBusy)}
		title="Remove this sync record?"
	>
		{#if removing}
			<div class="dialog-copy">
				<p>
					Only the record of where <code>{keyPlace(removing.key)}</code> was read up to is removed.
					Work items, people and docs stay in the graph.
				</p>
				{#if removeError}<p class="dialog-error" role="alert">{removeError}</p>{/if}
			</div>
		{/if}
		{#snippet footer()}
			<Button onclick={() => (removeOpen = false)} disabled={removeBusy}>Keep it</Button>
			<Button variant="danger" onclick={confirmRemove} loading={removeBusy}>Remove record</Button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
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
	.head-actions :global(.btn svg),
	.leftovers :global(.btn svg) {
		width: 1rem;
		height: 1rem;
	}
	.ledger {
		overflow-x: auto;
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	table {
		width: 100%;
		min-width: 56rem;
		border-collapse: collapse;
		font-size: var(--text-md);
	}
	thead th {
		padding: var(--space-2) var(--space-4);
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		color: var(--color-text-muted);
	}
	thead th:first-child {
		width: 30%;
	}
	.derived th,
	.derived td {
		padding: var(--space-3) var(--space-4);
		text-align: left;
		vertical-align: top;
		font-weight: var(--weight-regular);
		border-top: var(--border-hair) solid var(--color-line);
		background: var(--color-surface-sunken);
	}
	.name {
		display: flex;
		gap: var(--space-3);
	}
	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-md);
		border: var(--border-hair) dashed var(--color-line-strong);
		color: var(--color-text-muted);
	}
	.icon :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	.who {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.title {
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.faded {
		color: var(--color-text-muted);
	}
	.location,
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		overflow-wrap: anywhere;
	}
	.main,
	.sub {
		display: block;
	}
	.sub {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.tabular {
		font-variant-numeric: tabular-nums;
	}
	.leftovers {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.leftovers h2 {
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.leftovers p {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
		max-width: 70ch;
	}
	.leftovers ul {
		margin: 0;
		padding: 0;
		list-style: none;
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.leftovers li {
		display: grid;
		grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto;
		gap: var(--space-4);
		align-items: center;
		padding: var(--space-3) var(--space-4);
	}
	.leftovers li + li {
		border-top: var(--border-hair) solid var(--color-line);
	}
	@media (max-width: 720px) {
		.leftovers li {
			grid-template-columns: minmax(0, 1fr) auto;
		}
		.leftovers li .sub {
			grid-row: 2;
		}
	}
	.skeleton .block {
		height: 14rem;
		background: var(--color-surface-sunken);
		border-radius: var(--radius-md);
	}
	.dialog-copy {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.dialog-error {
		color: var(--color-danger);
	}
</style>
