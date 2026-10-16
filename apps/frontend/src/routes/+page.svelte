<!--
@component
The entry point: sends you to the company you used last, or shows the first-run state when there
are none yet. Why: every company page lives under `/c/<slug>/`, so `/` only decides which one.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { getCompanies } from '$lib/companies.svelte';
	import { EmptyState } from '$lib';

	const companies = getCompanies();

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
	<EmptyState
		title="Your first company brain will appear here"
		description="Add a company and Citadel builds a graph of its engineering activity."
	/>
{:else if !companies.ready && companies.error}
	<EmptyState title="Can't reach the Citadel API" description={companies.error} />
{:else}
	<p class="loading" role="status">Loading companies</p>
{/if}

<style>
	.loading {
		color: var(--color-text-muted);
	}
</style>
