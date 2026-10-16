<!--
@component
The dashboard frame: sidebar on the left, top bar, scrolling content. Below 900px the sidebar
becomes a drawer opened from the top bar. Provides the tooltip context for everything inside.
-->
<script lang="ts">
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';
	import Sidebar from './Sidebar.svelte';
	import Topbar from './Topbar.svelte';

	let { children }: { children: Snippet } = $props();
	let navOpen = $state(false);
	const close = () => (navOpen = false);
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && navOpen && close()} />

<Tooltip.Provider delayDuration={300}>
	<div class="shell">
		<div id="app-sidebar" class={['side', { open: navOpen }]}>
			<Sidebar onnavigate={close} />
		</div>
		{#if navOpen}
			<button class="scrim" type="button" aria-label="Close navigation" onclick={close}></button>
		{/if}
		<div class="main">
			<Topbar onmenu={() => (navOpen = !navOpen)} menuOpen={navOpen} />
			<main class="content">
				{@render children()}
			</main>
		</div>
	</div>
</Tooltip.Provider>

<style>
	.shell {
		display: grid;
		grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
		min-height: 100dvh;
	}
	.side {
		position: sticky;
		top: 0;
		height: 100dvh;
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
			width: min(var(--sidebar-width), 85vw);
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
