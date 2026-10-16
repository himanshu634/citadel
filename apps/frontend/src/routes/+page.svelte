<!--
@component
The entry point: sends you to the company you used last, or shows the first-run state when there
are none yet. Why: every company page lives under `/c/<slug>/`, so `/` only decides which one.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { getCompanies } from '$lib/companies.svelte';
	import { Plus } from '@lucide/svelte';
	import { Button, EmptyState } from '$lib';
	import { getAddCompany } from '$lib/addCompany.svelte';

	const companies = getCompanies();
	const adding = getAddCompany();

	function lastUsed(): string | null {
		try {
			return localStorage.getItem('citadel-company');
		} catch {
			return null;
		}
	}

	$effect(() => {
		if (!companies.ready || companies.list.length === 0) return;
		const last = lastUsed();
		const slug = companies.list.some((c) => c.slug === last) ? last! : companies.list[0].slug;
		void goto(resolve('/c/[slug]', { slug }), { replaceState: true });
	});
</script>

<svelte:head><title>Citadel</title></svelte:head>

{#if companies.ready && companies.list.length === 0}
	<div class="first-run">
		<h1>Company brains</h1>
		<EmptyState
			title="Your first company brain will appear here"
			description="Add a company and Citadel builds a graph of its engineering activity."
		>
			{#snippet action()}
				<Button variant="primary" aria-haspopup="dialog" onclick={() => adding.show()}>
					<Plus aria-hidden="true" />Add a company
				</Button>
			{/snippet}
		</EmptyState>
		<p class="demo">Want demo data first? Run <code>make synthetic</code> to load a small made-up company.</p>
	</div>
{:else if !companies.ready && companies.error}
	<EmptyState title="Can't reach the Citadel API" description={companies.error} />
{:else}
	<p class="loading" role="status">Loading companies</p>
{/if}

<style>
	.first-run {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}
	h1 {
		font-size: var(--text-2xl);
		font-variation-settings: 'wdth' var(--width-brand);
		font-weight: var(--weight-black);
	}
	.demo,
	.loading {
		color: var(--color-text-muted);
	}
</style>
