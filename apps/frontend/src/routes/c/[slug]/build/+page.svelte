<!--
@component
One company's build, live. Why: a build runs for minutes and the user may leave and come back, so
the page reads the build from the API and then follows its event stream (`BuildFeed`); it never
depends on having been here when the build started. Opened from the add-company flow
(`?from=new`) it shows that flow's steps with "Build" current.
-->
<script lang="ts">
	import { ArrowRight, Hammer, LoaderCircle, RotateCw } from '@lucide/svelte';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Banner, BuildProgress, Button, EmptyState, Stepper } from '$lib';
	import { BuildFeed } from '$lib/buildFeed.svelte';
	import { isActive, titleOf } from '$lib/buildProgress';
	import { getCompanies } from '$lib/companies.svelte';

	let { data } = $props();
	const companies = getCompanies();
	const feed = new BuildFeed();

	const company = $derived(companies.byslug(data.slug));
	const name = $derived(company?.name ?? data.slug);
	// A build started elsewhere (Sync now, a settings rebuild) changes this and is picked up.
	const startedAt = $derived(company?.build?.started_at ?? null);
	const fromNew = $derived(page.url.searchParams.get('from') === 'new');
	const companyPath = $derived(resolve(`/c/${data.slug}` as `/c/${string}`));

	$effect(() => {
		const slug = data.slug;
		void startedAt;
		// `open` reads the feed's own state; only the slug and a new build should re-run this.
		untrack(() => feed.open(slug));
		return () => feed.close();
	});

	// The feed holds the last company's build until the next read lands: show it only for this slug.
	const snapshot = $derived(feed.snapshot?.slug === data.slug ? feed.snapshot : null);
	const active = $derived(snapshot !== null && isActive(snapshot.state));
	const stopping = $derived(feed.stopping && active);
	const rebuild = $derived(snapshot?.kind === 'rebuild');
	const steps = [
		{ label: 'Company' },
		{ label: 'Sources' },
		{ label: 'Systems and people' },
		{ label: 'Build' }
	];
	// Steps of the pipeline, as the "What happens" list explains them.
	const happens = $derived([
		...(rebuild
			? [{ title: 'Reset', text: `Delete brain_${data.slug}, so the rebuild starts from nothing.` }]
			: []),
		{
			title: 'Prepare',
			text: `Create brain_${data.slug} and its indexes, including the vector index for answers.`
		},
		{
			title: 'Fetch',
			text: 'Download from each source into the cache. The only step that calls GitHub.'
		},
		{
			title: 'Records',
			text: 'Turn raw data into people, teams, systems, work items, changes and documents.'
		},
		{ title: 'Normalize', text: 'Apply the path rules, bots and the activity date.' },
		{
			title: 'Load',
			text: `Write into brain_${data.slug}. Links whose other end is missing are dropped and counted.`
		}
	]);
</script>

<svelte:head><title>Build {name} | Citadel</title></svelte:head>

<div class="page">
	<header class="page-head">
		<h1>{snapshot ? titleOf(name, snapshot) : `Build ${name}`}</h1>
		<p>
			Graph <code>brain_{data.slug}</code>.
			{#if active}
				You can leave this page or switch company; the build keeps going and the rail shows its progress.
			{/if}
		</p>
	</header>

	{#if fromNew}
		<Stepper {steps} current={3} done={[0, 1, 2]} label="Add a company" />
	{/if}

	{#if feed.error && snapshot}
		<Banner tone="danger" title="That didn't work">{feed.error}</Banner>
	{/if}

	{#if snapshot}
		<div class="layout">
			<BuildProgress {snapshot} {stopping}>
				{#snippet actions()}
					{#if active}
						<Button variant="ghost" disabled={stopping} onclick={() => feed.stop()}>
							{stopping ? 'Stopping' : 'Stop build'}
						</Button>
						<Button variant="primary" href={companyPath}>
							Go to {name}<ArrowRight aria-hidden="true" />
						</Button>
					{:else if snapshot.state === 'done'}
						<span></span>
						<Button variant="primary" href={companyPath}>
							Go to {name}<ArrowRight aria-hidden="true" />
						</Button>
					{:else}
						<Button href={companyPath}>Go to {name}</Button>
						<Button variant="primary" onclick={() => feed.start()}>
							<RotateCw aria-hidden="true" />
							{#if snapshot.state === 'failed'}
								{rebuild ? 'Retry rebuild' : 'Retry build'}
							{:else}
								{rebuild ? 'Rebuild again' : 'Build again'}
							{/if}
						</Button>
					{/if}
				{/snippet}
			</BuildProgress>

			<aside class="happens" aria-labelledby="happens-heading">
				<h2 id="happens-heading">What happens</h2>
				<ol>
					{#each happens as step (step.title)}
						<li>
							<b>{step.title}</b>
							<span>{step.text}</span>
						</li>
					{/each}
				</ol>
			</aside>
		</div>
	{:else if feed.missing}
		<EmptyState
			title="{name} has not been built yet"
			description="A build reads each source and writes people, work items and changes into brain_{data.slug}. It runs in the background, so you can leave this page."
		>
			{#snippet icon()}<Hammer />{/snippet}
			{#snippet action()}
				<Button variant="primary" onclick={() => feed.start(false)}>Start build</Button>
			{/snippet}
		</EmptyState>
		{#if feed.error}<Banner tone="danger" title="That didn't work">{feed.error}</Banner>{/if}
	{:else if feed.error}
		<EmptyState title="Can't read the build" description={feed.error}>
			{#snippet action()}<Button onclick={() => feed.open(data.slug)}>Try again</Button>{/snippet}
		</EmptyState>
	{:else}
		<p class="loading" role="status">
			<LoaderCircle aria-hidden="true" />Loading build
		</p>
	{/if}
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-width: 0;
	}
	h1 {
		font-size: var(--text-2xl);
		font-variation-settings: 'wdth' var(--width-brand);
		font-weight: var(--weight-black);
		overflow-wrap: anywhere;
	}
	.page-head p {
		margin-top: var(--space-1);
		color: var(--color-text-muted);
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 20rem;
		gap: var(--space-6);
		align-items: start;
	}
	.happens {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-5);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.happens h2 {
		font-size: var(--text-md);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.happens ol {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.happens li {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
	}
	.happens li span {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	@media (max-width: 1100px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.loading {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
	}
	.loading :global(svg) {
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
		.loading :global(svg) {
			animation: none;
		}
	}
</style>
