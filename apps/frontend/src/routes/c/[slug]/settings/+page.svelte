<!--
@component
One company's settings (`/c/<slug>/settings`): the three onboarding steps as one form, with the
graph name read-only. "Save" first asks the server what the change needs (`PUT ?dry_run=1`). A
change that only edits or adds saves at once; one that alters what belongs in the graph (the start
date, a removed source, rules) opens a dialog, and only "Save and rebuild" empties and rebuilds the
graph. A build in progress blocks a save with a message that links to its progress.

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
	import { Banner, Button, Card, CompanyForm, Dialog, EmptyState } from '$lib';
	import { cleanDraft, debounce, saveGate, visibleErrors, type Gate } from '$lib/onboarding';
	import { repoChecks } from '$lib/repochecks.svelte';
	import {
		classifySaveError,
		isDirty,
		rebuildDialog,
		settingsReason,
		syncLine,
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
		rejected = pending = null;
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
	});

	// --- What the person is told ---------------------------------------------------------------------
	const key = () => (form ? JSON.stringify(cleanDraft($state.snapshot(form.draft))) : '');

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
			saveError = 'The server found a problem with these settings. Fix the fields marked above.';
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
		<h1>Settings</h1>
		{#if company}
			<p>{company.name}, graph <code>brain_{company.slug}</code>.</p>
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

		<Card>
			<form class="form" onsubmit={(event) => { event.preventDefault(); void save(); }} novalidate>
				<fieldset class="fields" disabled={saving}>
					{#key f.slug}
						<CompanyForm bind:draft={f.draft} section="all" {errors} slugLocked />
					{/key}
				</fieldset>

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
				{#if why}<p class="why" role="status">{why}</p>{/if}

				<div class="foot">
					<Button onclick={syncNow} loading={syncing} disabled={company?.status === 'building'}>
						<RefreshCw aria-hidden="true" />Sync now
					</Button>
					<div class="save">
						{#if started === 'sync'}
							<p class="done" role="status">
								<Check aria-hidden="true" />Sync started. <a href={buildPath}>See progress</a>
							</p>
						{:else if saved && !dirty}
							<p class="done" role="status">
								<Check aria-hidden="true" />{saved}{#if started === 'build'}
									<a href={buildPath}>See progress</a>{/if}
							</p>
						{/if}
						<Button variant="primary" type="submit" loading={saving && !dialogOpen} disabled={!canSave}>
							Save
						</Button>
					</div>
				</div>
			</form>
		</Card>
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
	code {
		font-family: var(--font-mono);
	}
	.loading {
		color: var(--color-text-muted);
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.fields {
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.why {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.save {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
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
