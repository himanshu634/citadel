<!--
@component
Top bar: menu button (narrow screens), the ask field, the current company's status, theme. Below
900px the menu button is the current company's monogram tile, the same ink tile as on the rail, so
the drawer it opens reads as "this company's navigation". The ask field is closed while there is
nothing to ask (building, empty, unreachable, invalid) and says why in its placeholder.
-->
<script lang="ts">
	import { CircleAlert, CloudOff, LoaderCircle, Menu as MenuIcon, Search } from '@lucide/svelte';
	import type { Component } from 'svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import ThemeToggle from './ThemeToggle.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import { monogram } from '$lib/companies';
	import { askFieldOf, statusLineOf } from '$lib/topbar';

	type Props = { onmenu: () => void; menuOpen: boolean };
	let { onmenu, menuOpen }: Props = $props();

	const companies = getCompanies();
	const company = $derived(companies.currentCompany);
	const ask = $derived(askFieldOf(company));
	const status = $derived(statusLineOf(company));
	const mono = $derived.by(() => {
		const index = companies.list.findIndex((c) => c.slug === company?.slug);
		return index < 0 ? null : monogram(companies.list.map((c) => c.name), index);
	});
	// Status is never colour alone: the icon and the words say it too.
	const icon = $derived<Component | null>(
		company?.status === 'building'
			? LoaderCircle
			: company?.status === 'failed' || company?.status === 'invalid'
				? CircleAlert
				: company?.status === 'unknown'
					? CloudOff
					: null
	);
	let question = $state('');
	// A question typed for one company must not follow you to the next.
	$effect(() => {
		void companies.current;
		question = '';
	});
</script>

<header class="topbar">
	<button
		type="button"
		class={['menu-button', { tile: mono !== null }]}
		aria-label={company ? `Open navigation, ${company.name}` : 'Open navigation'}
		aria-expanded={menuOpen}
		aria-controls="app-sidebar"
		onclick={onmenu}
	>
		{#if mono !== null}
			<span class="mono" aria-hidden="true">{mono}</span>
		{:else}
			<MenuIcon aria-hidden="true" />
		{/if}
	</button>

	<form class="ask" role="search" onsubmit={(e) => e.preventDefault()}>
		<Input
			label="Ask the brain"
			hideLabel
			type="search"
			placeholder={ask.placeholder}
			disabled={ask.disabled}
			bind:value={question}
		>
			{#snippet leading()}<Search />{/snippet}
		</Input>
	</form>

	{#if status}
		<p class={['status', status.tone]}>
			{#if icon}
				{@const Icon = icon}
				<Icon class={{ spin: company?.status === 'building' }} aria-hidden="true" />
			{/if}
			<span>
				{#if status.datetime && status.when}
					Synced <time datetime={status.datetime}>{status.when}</time>
				{:else}
					{status.text}
				{/if}
			</span>
		</p>
	{/if}
	<ThemeToggle />
</header>

<style>
	.topbar {
		position: sticky;
		top: env(safe-area-inset-top, 0px);
		z-index: 20;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--topbar-height);
		padding-block: var(--space-2);
		padding-inline: max(var(--space-4), env(safe-area-inset-left, 0px))
			max(var(--space-4), env(safe-area-inset-right, 0px));
		background: var(--color-surface);
		border-bottom: var(--border-hair) solid var(--color-line);
	}
	.menu-button {
		display: none;
		flex: none;
		place-items: center;
		width: var(--control-md);
		height: var(--control-md);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		cursor: pointer;
	}
	.menu-button :global(svg) {
		width: 1.25rem;
		height: 1.25rem;
	}
	/* The rail's current-company tile: ink, never accent. */
	.menu-button.tile,
	.menu-button.tile:hover {
		width: var(--control-lg);
		height: var(--control-lg);
		border-color: var(--color-text);
		background: var(--color-text);
		color: var(--color-surface);
	}
	.mono {
		font-size: var(--rail-mark);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: 1;
	}
	.ask {
		flex: 1;
		max-width: 36rem;
		min-width: 0;
	}
	.status {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-left: auto;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		white-space: nowrap;
	}
	.status :global(svg) {
		width: 0.95rem;
		height: 0.95rem;
		flex: none;
	}
	.warning :global(svg) {
		color: var(--color-warning);
	}
	.danger {
		color: var(--color-danger);
		font-weight: var(--weight-semibold);
	}
	.status :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.status :global(.spin) {
			animation: none;
		}
	}
	@media (max-width: 900px) {
		.menu-button {
			display: grid;
		}
	}
	@media (max-width: 640px) {
		.topbar {
			flex-wrap: wrap;
		}
		.ask {
			order: 10;
			flex-basis: 100%;
			max-width: none;
		}
		.status {
			flex: 1;
			justify-content: flex-end;
			min-width: 0;
			white-space: normal;
			text-align: right;
		}
	}
</style>
