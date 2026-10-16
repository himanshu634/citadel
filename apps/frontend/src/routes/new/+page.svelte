<!--
@component
Add a company (`/new`): Company, Sources, Systems and people, then Save and build. The draft lives
here; every change is cleaned and sent to the validate endpoint after 300 ms, and the answer feeds
the errors under the fields, the Continue button and the YAML preview. Nothing is written until
"Save and build" (or "Skip, use defaults"), which creates the company and starts its first build.
-->
<script lang="ts">
	import { ArrowRight } from '@lucide/svelte';
	import { onDestroy, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ApiError, api, describeError } from '$lib/api/client';
	import { getCompanies } from '$lib/companies.svelte';
	import { Banner, Button, Card, CompanyForm, ConfigPreview, Stepper } from '$lib';
	import {
		SECTIONS,
		SECTION_KEYS,
		cleanDraft,
		continueGate,
		debounce,
		defaultDraft,
		firstSectionWithErrors,
		saveGate,
		type Gate
	} from '$lib/onboarding';
	import { repoChecks } from '$lib/repochecks.svelte';
	import type { CompanyConfig, FieldError, ValidateResult } from '$lib/types';

	const companies = getCompanies();

	let draft = $state<CompanyConfig>(defaultDraft(new Date()));
	let step = $state(0);
	const section = $derived(SECTIONS[step]);

	// --- Live validation ---------------------------------------------------------------------------
	let result = $state.raw<ValidateResult | null>(null);
	let lastYaml = $state('');
	let validating = $state(true);
	let apiProblem = $state<string | null>(null);
	let version = 0; // bumped on every edit: an answer for an older edit is dropped

	const validate = debounce(async (payload: CompanyConfig, mine: number) => {
		try {
			const answer = await api.validate(payload);
			if (mine !== version) return;
			result = answer;
			if (answer.yaml) lastYaml = answer.yaml;
			apiProblem = null;
		} catch (e) {
			if (mine !== version) return;
			apiProblem = describeError(e);
		}
		validating = false;
	}, 300);

	$effect(() => {
		const payload = cleanDraft($state.snapshot(draft));
		version += 1;
		validating = true;
		validate(payload, version);
	});
	onDestroy(() => {
		version += 1;
		validate.cancel();
	});

	// --- What the person is told ---------------------------------------------------------------------
	// A create the server turned down: the slug was taken, or the draft was invalid after all.
	let rejected = $state<{ key: string; errors: FieldError[] } | null>(null);
	const key = () => JSON.stringify(cleanDraft($state.snapshot(draft)));

	const errors = $derived.by<FieldError[]>(() => {
		const out = [...(result?.errors ?? [])];
		if (result?.slug_taken && result.slug_taken_detail) {
			out.push({ loc: ['slug'], msg: result.slug_taken_detail });
		}
		if (rejected && rejected.key === key()) out.push(...rejected.errors);
		return out;
	});
	const gate = $derived<Gate>({
		draft,
		errors,
		validating,
		answered: result !== null,
		unreachable: apiProblem !== null,
		fact: (repo) => repoChecks.fact(repo),
		repoPending: (repo) => repoChecks.pending(repo)
	});
	const here = $derived(continueGate(gate, section));
	const saveResult = $derived(saveGate(gate));
	const skipResult = $derived(saveGate(gate, true));
	// The footer line: why the button the person is looking at is shut.
	const why = $derived(step < SECTIONS.length - 1 ? here.reason : saveResult.reason);

	// --- Moving between steps ------------------------------------------------------------------------
	let formEl: HTMLElement | undefined = $state();
	async function go(to: number) {
		step = to;
		await tick();
		formEl?.querySelector<HTMLElement>('h2')?.focus();
	}
	function onsubmit(event: SubmitEvent) {
		event.preventDefault(); // Enter in a field moves on, but never saves
		if (step < SECTIONS.length - 1 && !here.blocked) void go(step + 1);
	}

	// --- Save and build ------------------------------------------------------------------------------
	let saving = $state(false);
	let saveError = $state<string | null>(null);
	/** The company exists but its first build did not start. */
	let started = $state<{ slug: string; name: string; problem: string } | null>(null);

	async function save(skipRules = false) {
		if (saving) return; // set before the first await, so a double click cannot start a second save
		saving = true;
		saveError = null;
		try {
			if (skipRules) {
				draft.systems = { rules: [], fallback: 'depth_2', ignore: [] };
				draft.people = { bots: [], aliases: {} };
			}
			const payload = cleanDraft($state.snapshot(draft));
			try {
				await api.create(payload);
			} catch (e) {
				await failedCreate(e);
				return;
			}
			await begin(payload.slug, payload.name);
		} finally {
			saving = false;
		}
	}

	async function failedCreate(e: unknown) {
		if (e instanceof ApiError && e.status === 409 && typeof e.detail === 'string') {
			rejected = { key: key(), errors: [{ loc: ['slug'], msg: e.detail }] };
			await go(0);
		} else if (e instanceof ApiError && e.status === 422 && Array.isArray(e.detail)) {
			const list = e.detail as FieldError[];
			rejected = { key: key(), errors: list };
			await go(Math.max(0, firstSectionWithErrors(list)));
		} else {
			saveError = describeError(e);
		}
	}

	/** Start the first build, then show the company. A failed start keeps the company and says so. */
	async function begin(slug: string, name: string) {
		try {
			await api.startBuild(slug);
		} catch (e) {
			// 409: a build for it is already running, which is what was wanted.
			if (!(e instanceof ApiError && e.status === 409)) {
				started = { slug, name, problem: describeError(e) };
				await companies.load();
				return;
			}
		}
		await companies.load();
		// The build page is its own route; `from=new` makes it show this wizard's Stepper at step 4.
		// resolve() has no entry for it yet.
		await goto(`${resolve('/c/[slug]', { slug })}/build?from=new`);
	}

	async function retryBuild() {
		if (saving || !started) return;
		saving = true;
		const { slug, name } = started;
		started = null;
		try {
			await begin(slug, name);
		} finally {
			saving = false;
		}
	}

	const home = resolve('/');
	const slugForTitle = $derived(draft.slug || 'new company');
</script>

<svelte:head><title>Add a company brain</title></svelte:head>

<div class="page">
	<header class="head">
		<h1>Add a company brain</h1>
		<p>
			{#if draft.name.trim()}{draft.name.trim()}, graph <code>brain_{slugForTitle}</code>.{:else}Citadel
				reads the sources you pick and builds one graph for this company. Graphs are never shared
				between companies.{/if}
		</p>
	</header>

	<Stepper
		label="Steps"
		steps={[
			{ label: 'Company' },
			{ label: 'Sources' },
			{ label: 'Systems and people', hint: 'Optional' },
			{ label: 'Build' }
		]}
		current={saving || started ? 3 : step}
		done={[0, 1, 2].filter((i) => i < step || (i === step && (saving || !!started)))}
	/>

	{#if apiProblem}
		<Banner tone="danger" title="Can't reach the Citadel API">
			{apiProblem}
		</Banner>
	{/if}

	<div class="onboard">
		<Card>
			<form class="form" {onsubmit} bind:this={formEl} novalidate>
				<fieldset class="fields" disabled={saving || !!started}>
					<CompanyForm bind:draft section={section} {errors} />
				</fieldset>

				{#if started}
					{@const saved = started}
					<Banner tone="danger" title="{saved.name} was saved, but its build did not start">
						{saved.problem}
						{#snippet action()}
							<Button size="sm" onclick={retryBuild} loading={saving}>Try again</Button>
							<Button size="sm" href={resolve('/c/[slug]', { slug: saved.slug })}>
								Go to {saved.name}
							</Button>
						{/snippet}
					</Banner>
				{:else}
					{#if saveError}
						<Banner tone="danger" title="Could not save {draft.name.trim() || 'the company'}">
							{saveError}
						</Banner>
					{/if}
					{#if why}<p class="why" role="status">{why}</p>{/if}
					<div class="foot">
						{#if step === 0}
							<Button variant="ghost" href={home}>Cancel</Button>
						{:else}
							<Button variant="ghost" onclick={() => go(step - 1)} disabled={saving}>Back</Button>
						{/if}
						{#if step < SECTIONS.length - 1}
							<Button variant="primary" type="submit" disabled={here.blocked}>
								Continue<ArrowRight aria-hidden="true" />
							</Button>
						{:else}
							<div class="actions">
								<Button onclick={() => save(true)} disabled={saving || skipResult.blocked}>
									Skip, use defaults
								</Button>
								<Button variant="primary" onclick={() => save()} loading={saving} disabled={saveResult.blocked}>
									Save and build<ArrowRight aria-hidden="true" />
								</Button>
							</div>
						{/if}
					</div>
				{/if}
			</form>
		</Card>

		<ConfigPreview
			yaml={lastYaml}
			highlight={SECTION_KEYS[section]}
			stale={!!result && !result.yaml}
		/>
	</div>
</div>

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
	}
	code {
		font-family: var(--font-mono);
	}
	.onboard {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 22rem;
		gap: var(--space-6);
		align-items: start;
	}
	.onboard > :global(:last-child) {
		position: sticky;
		top: calc(var(--topbar-height) + var(--space-4));
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
	.actions {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	@media (max-width: 64rem) {
		.onboard {
			grid-template-columns: minmax(0, 1fr);
		}
		.onboard > :global(:last-child) {
			position: static;
		}
	}
</style>
