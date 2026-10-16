<!--
@component
One source of a company, edited in place. GitHub: the repository (with a fixed `github.com/` in
front), the six things to read, a note when no GitHub token exists ("Check again"), what GitHub
said about the repository, and an error when GitHub cannot find it, or when it is private while the
data permission is not Own (the build refuses such a repository). Documents folder and JSONL
records: one path, relative to the Citadel folder. Errors for this card (`loc` starting `['sources', index]`) show under the field
they name; any other error of the card is listed at its foot.
-->
<script lang="ts">
	import { FileJson, Folder, GitBranch, Trash2 } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import Banner from '../ui/Banner.svelte';
	import Button from '../ui/Button.svelte';
	import Checkbox from '../ui/Checkbox.svelte';
	import Input from '../ui/Input.svelte';
	import {
		GITHUB_PARTS,
		SOURCE_KINDS,
		debounce,
		friendly,
		messageAt,
		normalizeRepo,
		parseRepo,
		repoErrorFor,
		unmatched
	} from '$lib/onboarding';
	import { repoChecks, type RepoChecks } from '$lib/repochecks.svelte';
	import type { FieldError, SourceConfig } from '$lib/types';

	type Props = {
		source: SourceConfig;
		index: number;
		dataPermission: string;
		errors: FieldError[];
		onremove: () => void;
		/** Where GitHub's answers live; the gallery passes fixed ones. */
		checks?: RepoChecks;
	};

	let {
		source = $bindable(),
		index,
		dataPermission,
		errors,
		onremove,
		checks = repoChecks
	}: Props = $props();

	const title = $derived(SOURCE_KINDS.find((k) => k.type === source.type)?.title ?? source.type);
	const Icon = $derived(
		source.type === 'github' ? GitBranch : source.type === 'local_docs' ? Folder : FileJson
	);
	const at = (field: string) => ['sources', index, field];

	// --- GitHub ----------------------------------------------------------------------------------
	const repo = $derived(typeof source.repo === 'string' ? source.repo.trim() : '');
	const include = $derived(Array.isArray(source.include) ? (source.include as string[]) : []);
	const result = $derived(checks.results.get(repo));
	const checking = $derived(checks.checking.has(repo));
	const checkError = $derived(repoErrorFor(checks.fact(repo), dataPermission));
	const repoError = $derived(messageAt(errors, at('repo')) ?? checkError);

	function has(part: string) {
		return include.includes(part);
	}
	function toggle(part: string, on: boolean) {
		// Keep the file's order whatever order the boxes are ticked in.
		source.include = GITHUB_PARTS.map((p) => p.part).filter((p) => (p === part ? on : has(p)));
	}

	// Ask GitHub once the person stops typing a repository that could exist.
	const ask = debounce((name: string) => void checks.check(name), 500);
	$effect(() => {
		if (source.type === 'github' && parseRepo(repo)) ask(repo);
		else ask.cancel();
		return () => ask.cancel();
	});
	onMount(() => {
		if (source.type === 'github') void checks.checkToken();
	});

	async function checkAgain() {
		await checks.checkToken();
		if (parseRepo(repo)) await checks.check(repo, true);
	}

	// --- The other fields' errors that no input of the card shows ----------------------------------
	const rest = $derived(
		unmatched(
			errors.filter((e) => e.loc[0] === 'sources' && e.loc[1] === index),
			[at('repo'), at('path'), at('include')]
		)
	);
</script>

<section class="card" aria-label="{title} {index + 1}">
	<div class="head">
		<Icon aria-hidden="true" />
		<b>{title}</b>
		<Button
			variant="ghost"
			size="sm"
			onclick={onremove}
			aria-label="Remove {title} {index + 1}"
		>
			<Trash2 aria-hidden="true" />Remove
		</Button>
	</div>

	{#if source.type === 'github'}
		<div class="field">
			<Input
				label="Repository"
				prefix="github.com/"
				placeholder="owner/name"
				autocomplete="off"
				spellcheck="false"
				bind:value={
					() => (typeof source.repo === 'string' ? source.repo : ''),
					(v) => (source.repo = normalizeRepo(v))
				}
				hint="Owner and name on github.com, like FalkorDB/FalkorDB."
				error={repoError}
			/>
			{#if !repoError}
				<p class={['check', { warn: result?.kind === 'rate_limited' || result?.kind === 'unreachable' }]} role="status">
					{#if checking}
						Checking GitHub
					{:else if result?.kind === 'found'}
						Found on GitHub, {result.private ? 'private' : 'public'}.
					{:else if result?.kind === 'rate_limited'}
						GitHub is limiting checks right now. Press Check again in a minute.
					{:else if result?.kind === 'unreachable'}
						Could not reach GitHub to check this repository.
					{/if}
				</p>
			{/if}
		</div>

		<fieldset class="parts">
			<legend>What to read</legend>
			<div class="checks">
				{#each GITHUB_PARTS as { part, label } (part)}
					<Checkbox {label} bind:checked={() => has(part), (on) => toggle(part, on)} />
				{/each}
			</div>
			{#if messageAt(errors, at('include'))}
				<p class="error">{messageAt(errors, at('include'))}</p>
			{/if}
		</fieldset>

		{#if checks.token === null}
			<Banner tone="warning" title="No GitHub token found">
				Citadel looks for <code>GITHUB_TOKEN</code> in <code>.env</code>, then for
				<code>gh auth token</code>. Add one, then check again. The build cannot read this repository
				without it.
				{#snippet action()}
					<Button size="sm" onclick={checkAgain}>Check again</Button>
				{/snippet}
			</Banner>
		{:else if result && (result.kind === 'rate_limited' || result.kind === 'unreachable')}
			<div><Button size="sm" onclick={checkAgain}>Check again</Button></div>
		{/if}
	{:else}
		<Input
			label={source.type === 'local_docs' ? 'Folder' : 'Folder with the JSONL files'}
			mono
			placeholder={source.type === 'local_docs' ? 'data/inbox/acme_labs/docs' : 'data/inbox/acme_labs/records'}
			autocomplete="off"
			spellcheck="false"
			bind:value={
				() => (typeof source.path === 'string' ? source.path : ''),
				(v) => (source.path = v)
			}
			hint={source.type === 'local_docs'
				? 'Markdown and text files on the machine that runs Citadel, relative to the Citadel folder. A missing folder only skips this source.'
				: 'Relative to the Citadel folder. A missing folder only skips this source.'}
			error={messageAt(errors, at('path'))}
		/>
	{/if}

	{#if rest.length > 0}
		<ul class="rest" role="alert">
			{#each rest as e, i (i)}
				<li>{friendly(e)} <code>{e.loc.slice(2).join('.')}</code></li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
		padding: var(--space-4);
		background: var(--color-surface-sunken);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.head > :global(svg) {
		width: 1.125rem;
		height: 1.125rem;
		flex: none;
		color: var(--color-text-muted);
	}
	.head b {
		flex: 1;
		font-variation-settings: 'wdth' var(--width-heading);
		font-weight: var(--weight-bold);
	}
	.head :global(.btn svg) {
		width: 1rem;
		height: 1rem;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.check {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		min-height: 0;
	}
	.check.warn {
		color: var(--color-warning);
	}
	.check:empty {
		display: none;
	}
	.parts {
		min-width: 0;
		border: 0;
		padding: 0;
	}
	legend {
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.checks {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
		gap: var(--space-2) var(--space-4);
	}
	.error,
	.rest {
		font-size: var(--text-xs);
		color: var(--color-danger);
	}
	.rest {
		margin: 0;
		padding-left: var(--space-4);
	}
	code {
		font-family: var(--font-mono);
	}
</style>
