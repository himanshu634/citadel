<!--
@component
Top bar: menu button (narrow screens), company switcher, the ask field, sync status, theme.
-->
<script lang="ts">
	import { ChevronsUpDown, Menu as MenuIcon, Search } from '@lucide/svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Menu from '$lib/components/ui/Menu.svelte';
	import ThemeToggle from './ThemeToggle.svelte';
	import { companies, lastSync } from '$lib/data/sample';

	type Props = { onmenu: () => void; menuOpen: boolean };
	let { onmenu, menuOpen }: Props = $props();

	let current = $state(companies[0].slug);
	let question = $state('');
	const currentName = $derived(companies.find((c) => c.slug === current)?.name ?? current);
	const items = $derived(
		companies.map((c) => ({
			value: c.slug,
			label: c.name,
			hint: `brain_${c.slug}`,
			selected: c.slug === current
		}))
	);
</script>

<header class="topbar">
	<div class="menu-button">
		<Button
			variant="ghost"
			iconOnly
			label="Open navigation"
			aria-expanded={menuOpen}
			aria-controls="app-sidebar"
			onclick={onmenu}
		>
			<MenuIcon aria-hidden="true" />
		</Button>
	</div>

	<Menu {items} heading="Company graph" onselect={(v) => (current = v)}>
		{#snippet trigger(props)}
			<Button {...props} variant="ghost" label="Company: {currentName}">
				<span class="company">{currentName}</span>
				<ChevronsUpDown aria-hidden="true" />
			</Button>
		{/snippet}
	</Menu>

	<form class="ask" role="search" onsubmit={(e) => e.preventDefault()}>
		<Input
			label="Ask the brain"
			hideLabel
			type="search"
			placeholder="Ask about people, systems or decisions"
			bind:value={question}
		>
			{#snippet leading()}<Search />{/snippet}
		</Input>
	</form>

	<p class="sync">Synced <time datetime={lastSync.replace(' ', 'T')}>{lastSync}</time></p>
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
	}
	.company {
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.ask {
		flex: 1;
		max-width: 36rem;
		min-width: 0;
	}
	.sync {
		margin-left: auto;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		white-space: nowrap;
	}
	@media (max-width: 900px) {
		.menu-button {
			display: block;
		}
	}
	@media (max-width: 640px) {
		.sync {
			display: none;
		}
		.topbar {
			flex-wrap: wrap;
		}
		.ask {
			order: 10;
			flex-basis: 100%;
			max-width: none;
		}
	}
</style>
