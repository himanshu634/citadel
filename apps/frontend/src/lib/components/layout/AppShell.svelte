<!--
@component
The dashboard frame: company rail and sidebar on the left, top bar, scrolling content. Below
900px the rail and sidebar become one drawer, side by side, opened from the top bar. Provides the
tooltip context for everything inside.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { AddCompany, setAddCompany } from '$lib/addCompany.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import AddCompanyDialog from '../brain/AddCompanyDialog.svelte';
	import CompanyRail from './CompanyRail.svelte';
	import Sidebar from './Sidebar.svelte';
	import Topbar from './Topbar.svelte';

	let { children }: { children: Snippet } = $props();
	// The Graph page is a full-bleed canvas: no content width cap, no padding (design-system.md).
	const bleed = $derived(page.url.pathname.endsWith('/graph'));
	const companies = getCompanies();
	let navOpen = $state(false);
	const close = () => (navOpen = false);
	// One add-a-company dialog for the app: the rail's + and "Add another" both open it.
	const adding = new AddCompany();
	setAddCompany(adding);

	async function created(slug: string) {
		await companies.load();
		// The build page is its own route; resolve() has no entry for it yet.
		await goto(`${resolve('/c/[slug]', { slug })}/build`);
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && navOpen && close()} />

<Tooltip.Provider delayDuration={300}>
	<div class="shell">
		<div id="app-sidebar" class={['side', { open: navOpen }]}>
			<CompanyRail
				companies={companies.list}
				current={companies.current}
				pathname={page.url.pathname}
				onnavigate={close}
				onadd={() => {
					close();
					adding.show();
				}}
			/>
			<div class="sidebar-slot"><Sidebar onnavigate={close} /></div>
		</div>
		{#if navOpen}
			<button class="scrim" type="button" aria-label="Close navigation" onclick={close}></button>
		{/if}
		<div class={['main', { bleed }]}>
			<Topbar onmenu={() => (navOpen = !navOpen)} menuOpen={navOpen} />
			<main class={['content', { bleed }]}>
				{@render children()}
			</main>
		</div>
	</div>
	<AddCompanyDialog ctl={adding} oncreated={created} />
</Tooltip.Provider>

<style>
	.shell {
		display: grid;
		grid-template-columns: calc(var(--rail-width) + var(--sidebar-width)) minmax(0, 1fr);
		min-height: 100dvh;
	}
	.side {
		position: sticky;
		top: 0;
		display: flex;
		height: 100dvh;
	}
	.sidebar-slot {
		flex: 1;
		min-width: 0;
	}
	.main {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.content {
		width: 100%;
		max-width: var(--content-max);
		margin-inline: auto;
		padding-block: var(--space-6) var(--space-12);
		padding-inline: max(var(--space-4), env(safe-area-inset-left, 0px))
			max(var(--space-4), env(safe-area-inset-right, 0px));
	}
	@media (min-width: 1100px) {
		.content {
			padding-inline: var(--space-8);
		}
	}
	/* The Graph page fills the window under the top bar, however tall the top bar wraps. */
	.main.bleed {
		height: 100dvh;
	}
	.content.bleed {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
		max-width: none;
		padding: 0;
	}
	.scrim {
		display: none;
	}
	@media (max-width: 900px) {
		.shell {
			grid-template-columns: minmax(0, 1fr);
		}
		.side {
			position: fixed;
			inset: 0 auto 0 0;
			z-index: 31;
			width: min(calc(var(--rail-width) + var(--sidebar-width)), 92vw);
			transform: translateX(-100%);
			transition: transform var(--duration-base) var(--ease-out);
			visibility: hidden;
		}
		.side.open {
			transform: none;
			visibility: visible;
		}
		.scrim {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 30;
			border: 0;
			background: var(--color-scrim);
		}
	}
</style>
