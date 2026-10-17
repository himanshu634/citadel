<!--
@component
One company's settings (`/c/<slug>/settings`): the three onboarding steps as three tabs (Company,
Sources, Systems and people) over one draft, with Sync now in the page header. A tab marks its
unsaved edits and counts its errors. Once something changed, a save bar says where, what saving
will do (a debounced `PUT ?dry_run=1` as you edit) and names the button for it: "Save" or "Save
and rebuild". "Save" asks the server again: a change that only edits or adds saves at once; one
that alters what belongs in the graph (the start date, a removed source, rules) opens a dialog, and
only "Save and rebuild" there empties and rebuilds the graph. A build in progress blocks a save
with a message that links to its progress.

Why: the page is one component for every company, so everything it holds belongs to the slug it
loaded. A switch resets it, and answers that arrive for the company you left are dropped.
-->
<script lang="ts">
	import { Check, RefreshCw } from '@lucide/svelte';
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import { Banner, Button, Card, CompanyForm, Dialog, Tabs } from '$lib';
	import {
		SECTIONS,
		STEP_NAMES,
		cleanDraft,
		debounce,
		errorsIn,
		firstSectionWithErrors,
		saveGate,
		sourceErrors,
		visibleErrors,
		type Gate,
		type Section
	} from '$lib/onboarding';
	import { repoChecks } from '$lib/repochecks.svelte';
	import {
		changedSections,
		classifySaveError,
		isDirty,
		rebuildDialog,
		saveCost,
		settingsReason,
		syncLine,
		unsavedLine,
		type RebuildDialog
	} from '$lib/settings';
	import { startSync } from '$lib/sync';
	import type { CompanyConfig, ConfigChange, FieldError, ValidateResult } from '$lib/types';

	let { data } = $props();
	const companies = getCompanies();

	const company = $derived(companies.byslug(data.slug));
	const buildPath = $derived(resolve(`/c/${data.slug}/build` as `/c/${string}`));

	/** The loaded config and the draft being edited; always for the slug in `slug`. */
	type Form = { slug: string; loaded: CompanyConfig; draft: CompanyConfig };
	let form = $state<Form | null>(null);
	let loadError = $state<string | null>(null);
	let reload = $state(0);
	let tab = $state<Section>('company');
	// Bumped by Discard: the form is mounted again, so its local rows reseed from the saved config.
	let mount = $state(0);

	// Everything below belongs to the company in `form`. `run` is bumped on every switch, so a
	// request that finishes afterwards sees it is stale and changes nothing.
	let run = 0;
	let result = $state.raw<ValidateResult | null>(null);
	let apiProblem = $state<string | null>(null);
	let validating = $state(true);
	let version = 0; // bumped on every edit: an answer for an older edit is dropped

	let saving = $state(false);
	let syncing = $state(false);
	let saved = $state<string | null>(null);
	let started = $state<string | null>(null); // "Sync started" after Sync now
	let saveError = $state<string | null>(null);
	let running = $state(false); // the server refused: a build for this company is running
	let rejected = $state<{ key: string; errors: FieldError[] } | null>(null);
	let pending = $state.raw<{
		slug: string;
		payload: CompanyConfig;
		change: ConfigChange;
		dialog: RebuildDialog;
	} | null>(null);
	let dialogOpen = $state(false);
	/** The dry run's answer and the draft it was asked for. */
	let estimate = $state.raw<{ key: string; change: ConfigChange } | null>(null);

	// --- Load ----------------------------------------------------------------------------------------
	$effect(() => {
		const slug = data.slug;
		void reload;
		run += 1;
		version += 1;
		form = null;
		loadError = null;
		result = null;
		apiProblem = null;
		validating = true;
		saving = syncing = running = dialogOpen = false;
		saved = started = saveError = null;
		rejected = pending = estimate = null;
		tab = 'company';
		let live = true;
		api.company(slug).then(
			(answer) => {
				const mine = companies.guard(slug, answer);
				if (!live || !mine) return;
				form = {
					slug,
					loaded: mine.config,
					draft: JSON.parse(JSON.stringify(mine.config)) as CompanyConfig
				};
			},
			(e) => {
				if (live && slug === companies.current) loadError = describeError(e);
			}
		);
		return () => {
			live = false;
		};
	});

	// --- Live validation (the same wiring as the add-company page) ---------------------------------
	const validate = debounce(async (payload: CompanyConfig, mine: number) => {
		try {
			const answer = await api.validate(payload);
			if (mine !== version) return;
			result = answer;
			apiProblem = null;
		} catch (e) {
			if (mine !== version) return;
			apiProblem = describeError(e);
		}
		validating = false;
	}, 300);

	$effect(() => {
		if (!form) return;
		const payload = cleanDraft($state.snapshot(form.draft));
		version += 1;
		validating = true;
		validate(payload, version);
	});
	onDestroy(() => {
		run += 1;
		version += 1;
		validate.cancel();
		askCost.cancel();
	});

	// --- What the person is told ---------------------------------------------------------------------
	const key = () => (form ? JSON.stringify(cleanDraft($state.snapshot(form.draft))) : '');
	const draftKey = $derived(key());

	// The slug is read-only here, and the server says it is "taken" by this very company: not shown.
	const errors = $derived.by<FieldError[]>(() => {
		const out = [...(result?.errors ?? [])];
		if (rejected && rejected.key === key()) out.push(...rejected.errors);
		return out;
	});
	const dirty = $derived(form ? isDirty(form.draft, form.loaded) : false);
	// The same gates as the add-company page, over all three sections at once. The field errors
	// shown are the ones the gate counts; a GitHub check still pending also keeps Save shut.
	const gate = $derived.by<Gate | null>(() =>
		form
			? {
					draft: form.draft,
					errors: visibleErrors(form.draft, errors),
					validating,
					answered: result !== null,
					unreachable: apiProblem !== null,
					fact: (repo) => repoChecks.fact(repo),
					repoPending: (repo) => repoChecks.pending(repo)
				}
			: null
	);
	const gateResult = $derived(gate ? saveGate(gate) : null);
	const canSave = $derived(!!gateResult && !gateResult.blocked && dirty && !saving);
	const why = $derived(dirty && !saving ? settingsReason(gateResult?.reason ?? null) : null);

	// --- Per tab: unsaved edits and errors ------------------------------------------------------------
	const changed = $derived(form ? changedSections(form.draft, form.loaded) : []);
	const tabs = $derived(
		SECTIONS.map((s) => {
			const shown = form ? errorsIn(visibleErrors(form.draft, errors), s).length : 0;
			const repo = form && s === 'sources' ? sourceErrors(form.draft, (r) => repoChecks.fact(r)).length : 0;
			return {
				value: s,
				label: STEP_NAMES[s],
				count: s === 'sources' ? form?.draft.sources.length : undefined,
				dirty: changed.includes(s),
				errors: shown + repo
			};
		})
	);

	// --- What saving will cost, asked as you edit -------------------------------------------------------
	const askCost = debounce(async (slug: string, payload: CompanyConfig, asked: string, mine: number) => {
		try {
			const change = await api.update(slug, payload, { dryRun: true });
			if (mine === run) estimate = { key: asked, change };
		} catch {
			// A refused dry run says nothing about the cost; Save asks again and explains.
		}
	}, 400);

	$effect(() => {
		if (!form || !canSave) return;
		askCost(form.slug, JSON.parse(draftKey) as CompanyConfig, draftKey, run);
	});
	const cost = $derived(estimate && estimate.key === draftKey ? saveCost(estimate.change) : null);

	// --- Save ------------------------------------------------------------------------------------------
	function clearMessages() {
		saved = started = saveError = null;
		running = false;
	}

	/** The server turned the save down; say why (a rebuild it asks for goes to the dialog). */
	function refused(e: unknown, slug: string, payload: CompanyConfig): void {
		const problem = classifySaveError(e);
		if (problem.kind === 'rebuild') {
			ask(slug, payload, problem.change);
		} else if (problem.kind === 'running') {
			dialogOpen = false;
			pending = null;
			running = true;
		} else if (problem.kind === 'invalid') {
			dialogOpen = false;
			pending = null;
			rejected = { key: JSON.stringify(payload), errors: problem.errors };
			const first = firstSectionWithErrors(problem.errors);
			if (first >= 0) tab = SECTIONS[first];
			saveError = `The server found a problem with these settings. Fix the fields marked in ${STEP_NAMES[tab]}.`;
		} else {
			saveError = problem.message;
		}
	}

	function ask(slug: string, payload: CompanyConfig, change: ConfigChange) {
		const name = payload.name || company?.name || slug;
		pending = { slug, payload, change, dialog: rebuildDialog(name, change) };
		dialogOpen = true;
	}

	async function save() {
		const current = form;
		// Set before the first await, so a double click cannot send a second request.
		if (saving || !current || !canSave) return;
		saving = true;
		clearMessages();
		const mine = run;
		const { slug } = current;
		const payload = cleanDraft($state.snapshot(current.draft));
		try {
			const change = await api.update(slug, payload, { dryRun: true });
			if (mine !== run) return;
			if (!change.changed) {
				saved = 'Nothing to save';
				current.loaded = payload;
			} else if (change.rebuild) {
				ask(slug, payload, change);
			} else {
				const detail = await api.update(slug, payload);
				void companies.load();
				if (mine !== run) return;
				current.loaded = detail.config;
				saved = syncLine(change.refetch);
				started = change.refetch.length > 0 ? 'build' : null;
			}
		} catch (e) {
			if (mine === run) refused(e, slug, payload);
		} finally {
			if (mine === run) saving = false;
		}
	}

	async function confirmRebuild() {
		const target = pending;
		const current = form;
		if (saving || !target || !current) return;
		saving = true;
		saveError = null;
		const mine = run;
		try {
			await api.update(target.slug, target.payload, { rebuild: true });
		} catch (e) {
			if (mine === run) {
				refused(e, target.slug, target.payload);
				saving = false;
			}
			return;
		}
		// The config is saved and the rebuild runs: nothing below may report a failed save.
		void companies.load();
		if (mine !== run) return;
		current.loaded = target.payload;
		dialogOpen = false;
		pending = null;
		try {
			await goto(buildPath);
		} catch {
			saved = 'Saved. The rebuild started.';
			started = 'build';
		}
		if (mine === run) saving = false;
	}

	function discard() {
		if (saving || !form) return;
		form.draft = JSON.parse(JSON.stringify(form.loaded)) as CompanyConfig;
		rejected = null;
		clearMessages();
		mount += 1;
	}

	function cancelRebuild() {
		if (saving) return;
		dialogOpen = false;
		pending = null;
	}

	// --- Sync now ----------------------------------------------------------------------------------------
	async function syncNow() {
		if (syncing || !form) return;
		syncing = true;
		clearMessages();
		const mine = run;
		const outcome = await startSync(form.slug);
		void companies.load();
		if (mine !== run) return;
		if (outcome.kind === 'started') started = 'sync';
		else if (outcome.kind === 'running') running = true;
		else saveError = outcome.message;
		syncing = false;
	}
</script>

<svelte:head><title>Settings | {company?.name ?? 'Company'} | Citadel</title></svelte:head>

<div class="page">
	<header class="head">
		<div>
			<h1>Settings</h1>
			{#if company}
				<p>{company.name}, graph <code>brain_{company.slug}</code>.</p>
			{/if}
		</div>
		{#if form}
			<div class="head-actions">
				{#if started === 'sync'}
					<p class="done" role="status">
						<Check aria-hidden="true" />Sync started. <a href={buildPath}>See progress</a>
					</p>
				{/if}
				<Button onclick={syncNow} loading={syncing} disabled={company?.status === 'building'}>
					<RefreshCw aria-hidden="true" />Sync now
				</Button>
			</div>
		{/if}
	</header>

	{#if loadError}
		<Banner tone="danger" title="Can't load these settings">
			{company?.status === 'invalid' && company.error ? company.error : loadError}
			{#snippet action()}<Button size="sm" onclick={() => reload++}>Try again</Button>{/snippet}
		</Banner>
	{:else if !form}
		<p class="loading" role="status">Loading settings</p>
	{:else}
		{@const f = form}
		{#if apiProblem}
			<Banner tone="danger" title="Can't reach the Citadel API">{apiProblem}</Banner>
		{/if}
		{#if running}
			<Banner tone="warning" title="A build is running. Wait for it or stop it, then save again.">
				{#snippet action()}<Button size="sm" href={buildPath}>See progress</Button>{/snippet}
			</Banner>
		{/if}
		{#if saveError}
			<Banner tone="danger" title="Could not save {f.draft.name.trim() || 'the company'}">
				{saveError}
			</Banner>
		{/if}

		<form class="form" onsubmit={(event) => { event.preventDefault(); void save(); }} novalidate>
			<fieldset class="fields" disabled={saving}>
				<Tabs items={tabs} bind:value={() => tab, (v) => (tab = v as Section)} label="Settings sections">
					{#snippet panel(value)}
						<Card>
							{#key `${f.slug}:${mount}`}
								<CompanyForm bind:draft={f.draft} section={value as Section} {errors} existing />
							{/key}
						</Card>
					{/snippet}
				</Tabs>
			</fieldset>

			{#if dirty}
				<div class="bar" role="region" aria-label="Unsaved changes">
					<div class="bar-text">
						<p class="bar-title">{unsavedLine(changed)}</p>
						{#if why}
							<p class="why" role="status">
								{why.text}
								{#if why.section && why.section !== tab}
									{@const go = why.section}
									<button type="button" class="link" onclick={() => (tab = go)}>
										Go to {STEP_NAMES[go]}
									</button>
								{/if}
							</p>
						{:else if cost}
							<p class="cost" class:rebuild={cost.rebuild}>{cost.line}</p>
						{/if}
					</div>
					<Button onclick={discard} disabled={saving}>Discard</Button>
					<Button variant="primary" type="submit" loading={saving && !dialogOpen} disabled={!canSave}>
						{cost?.label ?? 'Save'}
					</Button>
				</div>
			{:else if saved}
				<p class="done" role="status">
					<Check aria-hidden="true" />{saved}{#if started === 'build'}
						<a href={buildPath}>See progress</a>{/if}
				</p>
			{/if}
		</form>
	{/if}
</div>

{#if pending}
	<!-- Escape, the X and a click outside keep the dialog open while the rebuild request is on its way. -->
	<Dialog
		bind:open={() => dialogOpen, (value) => (dialogOpen = value || saving)}
		title={pending.dialog.title}
	>
		<div class="dialog-copy">
			{#if pending.dialog.reasons.length > 0}
				<ul>
					{#each pending.dialog.reasons as reason, i (i)}<li>{reason}</li>{/each}
				</ul>
			{/if}
			<p>{pending.dialog.explanation}</p>
			{#if pending.dialog.refetch}<p>{pending.dialog.refetch}</p>{/if}
			{#if saveError}<p class="dialog-error" role="alert">{saveError}</p>{/if}
		</div>
		{#snippet footer()}
			<Button onclick={cancelRebuild} disabled={saving}>Cancel</Button>
			<Button variant="primary" onclick={confirmRebuild} loading={saving}>Save and rebuild</Button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.head {
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
	.head p {
		margin-top: var(--space-1);
		color: var(--color-text-muted);
		overflow-wrap: anywhere;
	}
	.head-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.head-actions .done {
		margin-top: 0;
	}
	code {
		font-family: var(--font-mono);
	}
	.loading {
		color: var(--color-text-muted);
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.fields {
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	/* The save bar stays in view while the tab scrolls; it only exists while something changed. */
	.bar {
		position: sticky;
		bottom: var(--space-4);
		z-index: 2;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	.bar-text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin-right: auto;
		min-width: 0;
	}
	.bar-title {
		font-weight: var(--weight-semibold);
	}
	.why,
	.cost {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.cost.rebuild {
		color: var(--color-warning);
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-text);
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}
	.done {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.done :global(svg) {
		width: 1rem;
		height: 1rem;
		flex: none;
	}
	.done a {
		color: var(--color-text);
		text-decoration: underline;
	}
	.dialog-copy {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.dialog-copy ul {
		margin: 0;
		padding-left: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.dialog-error {
		color: var(--color-danger);
	}
</style>
