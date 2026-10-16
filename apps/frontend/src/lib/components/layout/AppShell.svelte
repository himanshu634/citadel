<!--
@component
The dashboard frame: company rail and sidebar on the left, top bar, scrolling content. The top
bar's fold button (or the [ key) folds the sidebar to its icons; the choice is kept in this
browser (`citadel-sidebar`). Below 900px the rail and sidebar become one drawer, side by side,
opened from the top bar, and the sidebar is never folded there (the kept choice comes back
above 900px; `[` does nothing below it). Provides the tooltip context for
everything inside.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { MediaQuery } from 'svelte/reactivity';
	import { AddCompany, setAddCompany } from '$lib/addCompany.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import AddCompanyDialog from '../brain/AddCompanyDialog.svelte';
	import CompanyRail from './CompanyRail.svelte';
	import Sidebar from './Sidebar.svelte';
	import Topbar from './Topbar.svelte';

	let { children }: { children: Snippet } = $props();
	// Graph and Ask fill the window under the top bar: no content width cap, no padding (design-system.md).
	const bleed = $derived(/\/(graph|ask)$/.test(page.url.pathname));
	const companies = getCompanies();
	let navOpen = $state(false);
	const close = () => (navOpen = false);

	const FOLD_KEY = 'citadel-sidebar';
	let folded = $state(false);
	// Read once in the browser: storage can be blocked (private window), and then it stays open.
	$effect(() => {
		try {
			folded = localStorage.getItem(FOLD_KEY) === 'folded';
		} catch {
			// keep it open
		}
	});
	function fold() {
		folded = !folded;
		try {
			localStorage.setItem(FOLD_KEY, folded ? 'folded' : 'open');
		} catch {
			// not remembered; it still folds for this visit
		}
	}
	// The drawer (900px and below, the same query as the CSS) is never folded; the choice is kept.
	const narrow = new MediaQuery('(max-width: 900px)');
	const sideFolded = $derived(folded && !narrow.current);
	const typing = (t: EventTarget | null) =>
		t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));
	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && navOpen) close();
		if (e.key === '[' && !narrow.current && !e.metaKey && !e.ctrlKey && !e.altKey && !typing(e.target)) fold();
	}
	// One add-a-company dialog for the app: the rail's + and "Add another" both open it.
	const adding = new AddCompany();
	setAddCompany(adding);

	async function created(slug: string) {
		await companies.load();
		// The build page is its own route; resolve() has no entry for it yet.
		await goto(`${resolve('/c/[slug]', { slug })}/build`);
	}
</script>

<svelte:window {onkeydown} />

<Tooltip.Provider delayDuration={300}>
	<div class={['shell', { folded: sideFolded }]}>
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
			<div class="sidebar-slot"><Sidebar onnavigate={close} folded={sideFolded} /></div>
		</div>
		{#if navOpen}
			<button class="scrim" type="button" aria-label="Close navigation" onclick={close}></button>
		{/if}
		<div class={['main', { bleed }]}>
			<Topbar onmenu={() => (navOpen = !navOpen)} menuOpen={navOpen} {folded} onfold={fold} />
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
	.shell.folded {
		grid-template-columns: calc(var(--rail-width) + var(--sidebar-folded)) minmax(0, 1fr);
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
		.shell,
		.shell.folded {
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
