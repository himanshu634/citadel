<!--
@component
Add a company from one public GitHub repository (direction D, "Paste and go"). One field; once
GitHub has answered, a summary of what Citadel will make (company, graph, what it reads), then
"Add and build". The states that stop it each say what to do: no token, not found, private
(Citadel reads public repositories only), and a company that already reads the repo or its owner.
State lives in `ctl` (an `AddCompany`); `oncreated` gets the slug whose build page to show.
-->
<script lang="ts">
	import { ArrowRight, Check } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { PRIVATE_MESSAGE, type AddCompany } from '$lib/addCompany.svelte';
	import Banner from '../ui/Banner.svelte';
	import Button from '../ui/Button.svelte';
	import Dialog from '../ui/Dialog.svelte';
	import Input from '../ui/Input.svelte';

	type Props = {
		ctl: AddCompany;
		oncreated?: (slug: string) => void;
	};
	let { ctl, oncreated }: Props = $props();

	const view = $derived(ctl.view);
	const found = $derived(ctl.found);
	let editing = $state(false);

	const fieldError = $derived(
		view === 'private'
			? `${ctl.repo} is private. ${PRIVATE_MESSAGE}`
			: view === 'missing'
				? `GitHub has no public repository ${ctl.repo}. Check the spelling.`
				: undefined
	);
	const fieldHint = $derived(
		view === 'typing'
			? 'Paste a link, or type owner/name.'
			: view === 'checking'
				? `Looking up ${ctl.repo} on GitHub…`
				: view === 'empty'
					? 'A link like github.com/FalkorDB/FalkorDB, or just FalkorDB/FalkorDB.'
					: undefined
	);
	// Only the window start is shown; the API picked it.
	const since = $derived(
		found?.since
			? new Date(`${found.since}T00:00:00`).toLocaleDateString('en-GB', {
					day: 'numeric',
					month: 'short',
					year: 'numeric'
				})
			: ''
	);

	async function finish(slug: string | null) {
		if (slug === null) return;
		ctl.open = false;
		oncreated?.(slug);
	}

	function onsubmit(event: SubmitEvent) {
		event.preventDefault(); // Enter adds, when it may
		if (ctl.canCreate) void ctl.create().then(finish);
	}
</script>

<Dialog
	bind:open={ctl.open}
	initialFocus="#add-company input"
	placement="top"
	title="Add a company brain"
	description="Paste a public GitHub repository. Citadel reads its activity into a new graph of its own."
>
	<form id="add-company" class="body" {onsubmit} novalidate>
		<Input
			label="GitHub repository"
			value={ctl.text}
			oninput={(e) => ctl.input(e.currentTarget.value)}
			placeholder="owner/name or a GitHub link"
			autocomplete="off"
			spellcheck={false}
			mono
			hint={fieldHint}
			error={fieldError}
			disabled={ctl.busy}
		/>

		{#if view === 'no_token'}
			<Banner tone="warning" title="Citadel has no GitHub token">
				Set <code>GITHUB_TOKEN</code> in <code>.env</code> or run <code>gh auth login</code>, then
				check again.
				{#snippet action()}<Button size="sm" onclick={() => ctl.retry()}>Check again</Button>{/snippet}
			</Banner>
		{:else if view === 'rate_limited' || view === 'unreachable'}
			<Banner
				tone="danger"
				title={view === 'rate_limited' ? 'GitHub rate limit reached' : "GitHub didn't answer"}
			>
				{view === 'rate_limited' ? 'Wait a minute, then try again.' : 'Try again in a moment.'}
				{#snippet action()}<Button size="sm" onclick={() => ctl.retry()}>Try again</Button>{/snippet}
			</Banner>
		{:else if view === 'taken' && found?.company}
			{@const owner = found.company}
			<Banner tone="neutral" title="{owner.name} already reads this repository">
				Its graph is <code>brain_{owner.slug}</code>.
				{#snippet action()}
					<Button
						size="sm"
						href={resolve('/c/[slug]', { slug: owner.slug })}
						onclick={() => (ctl.open = false)}>Open {owner.name}</Button
					>
				{/snippet}
			</Banner>
		{:else if found && (view === 'ready' || view === 'owner')}
			{#if view === 'owner' && found.owner_company}
				{@const owner = found.owner_company}
				<Banner tone="neutral" title="{owner.name} already has a brain">
					Add this repository to <code>brain_{owner.slug}</code>, or make a separate company below.
					{#snippet action()}
						<Button
							size="sm"
							loading={ctl.busy}
							onclick={() => ctl.addTo(owner.slug).then(finish)}>Add to {owner.name}</Button
						>
					{/snippet}
				</Banner>
			{/if}
			<dl class="summary">
				<dt>Company</dt>
				<dd>
					{#if editing}
						<Input
							label="Company name"
							hideLabel
							value={ctl.companyName}
							oninput={(e) => (ctl.name = e.currentTarget.value)}
							onkeydown={(e) => e.key === 'Enter' && (editing = false)}
						/>
					{:else}
						<b>{ctl.companyName}</b>
					{/if}
				</dd>
				<dd class="edit">
					<button type="button" class="link" onclick={() => (editing = !editing)}>
						{editing ? 'Done' : 'Edit'}
					</button>
				</dd>
				<dt>Graph</dt>
				<dd><code>brain_{found.slug}</code></dd>
				<dd class="ok"><Check aria-hidden="true" />Public repo</dd>
				<dt>Reads</dt>
				<dd class="wide">
					Activity since {since}: commits, pull requests, issues, reviews, CODEOWNERS and docs.
					Change it later in Settings.
				</dd>
			</dl>
		{/if}

		{#if ctl.error}
			<p class="error" role="alert">{ctl.error}</p>
		{/if}
	</form>

	{#snippet footer()}
		<Button
			class="grow"
			variant="ghost"
			size="sm"
			href={resolve('/new')}
			onclick={() => (ctl.open = false)}>Advanced setup</Button
		>
		<Button variant="ghost" onclick={() => (ctl.open = false)}>Cancel</Button>
		<Button
			variant="primary"
			type="submit"
			form="add-company"
			loading={ctl.busy}
			disabled={!ctl.canCreate}
		>
			{view === 'owner' ? 'Add as a separate company' : 'Add and build'}
			<ArrowRight aria-hidden="true" />
		</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	code {
		font-family: var(--font-mono);
	}
	.summary {
		display: grid;
		grid-template-columns: 5.5rem minmax(0, 1fr) auto;
		gap: var(--space-2) var(--space-3);
		align-items: baseline;
		margin: 0;
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-size: var(--text-sm);
	}
	dt {
		color: var(--color-text-muted);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	dd {
		margin: 0;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.wide {
		grid-column: 2 / -1;
	}
	.edit {
		justify-self: end;
	}
	.ok {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-success);
		font-weight: var(--weight-semibold);
		white-space: nowrap;
	}
	.ok :global(svg) {
		width: 0.9rem;
		height: 0.9rem;
	}
	.link {
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--color-accent);
		font: inherit;
		font-weight: var(--weight-semibold);
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}
	.error {
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	:global(.dialog-foot) > :global(.grow) {
		margin-right: auto;
	}
</style>
