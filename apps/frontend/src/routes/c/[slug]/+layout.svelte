<!--
@component
The frame for every `/c/<slug>/` page: makes the route's company the current one, remembers it for
the next visit, and shows "not found" for a slug the API does not list. Pages render only for a
company that exists, so no page ever reads data for a made-up slug.
-->
<script lang="ts">
	import { resolve } from '$app/paths';
	import { getCompanies } from '$lib/companies.svelte';
	import { Button, EmptyState } from '$lib';

	let { data, children } = $props();
	const companies = getCompanies();

	const known = $derived(companies.byslug(data.slug) !== undefined);

	// Follows the route param; the cleanup clears it when the user leaves `/c/`.
	$effect(() => {
		companies.current = data.slug;
		return () => {
			companies.current = null;
		};
	});

	// Only a company the API lists becomes "last used", so `/` never redirects to a dead slug.
	$effect(() => {
		if (!known) return;
		try {
			localStorage.setItem('citadel-company', data.slug);
		} catch {
			// Storage can be blocked (private window); the redirect then falls back to the first company.
		}
	});
</script>

{#if companies.ready}
	{#if known}
		{@render children()}
	{:else}
		<EmptyState title="No company called {data.slug}" description="It may have been removed, or the link has a typo.">
			{#snippet action()}
				<Button href={resolve('/')}>See all companies</Button>
			{/snippet}
		</EmptyState>
	{/if}
{:else if companies.error}
	<EmptyState title="Can't reach the Citadel API" description={companies.error} />
{:else}
	<p class="loading" role="status">Loading companies</p>
{/if}

<style>
	.loading {
		color: var(--color-text-muted);
	}
</style>
