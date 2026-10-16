<script lang="ts">
	import '@fontsource-variable/archivo/wdth.css';
	import '@fontsource/ibm-plex-mono/400.css';
	import '@fontsource/ibm-plex-mono/500.css';
	import '$lib/styles/tokens.css';
	import '$lib/styles/base.css';
	import favicon from '$lib/assets/favicon.svg';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import { Companies, setCompanies } from '$lib/companies.svelte';
	import { Theme, setTheme } from '$lib/theme.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();
	setTheme(new Theme());
	const companies = new Companies();
	setCompanies(companies);
	// Reads the list and follows live status events; the returned stopper closes the stream.
	onMount(() => companies.start());
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Citadel</title>
</svelte:head>

<AppShell>
	{@render children()}
</AppShell>
