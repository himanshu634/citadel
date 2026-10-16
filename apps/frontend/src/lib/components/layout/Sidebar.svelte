<!--
@component
Primary navigation. The current page is the solid ultramarine block: the one loud element in
the shell. Sections that are not built yet stay visible but inert, marked "Soon". `folded` shows
the icons only (`--sidebar-folded` wide), each named by a tooltip and for screen readers.
-->
<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		BookOpen,
		Boxes,
		LayoutDashboard,
		MessageSquareText,
		Network,
		Palette,
		Settings,
		Users
	} from '@lucide/svelte';
	import type { Component } from 'svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import Tooltip from '../ui/Tooltip.svelte';

	type Props = { onnavigate?: () => void; folded?: boolean };
	let { onnavigate, folded = false }: Props = $props();

	const companies = getCompanies();
	const slug = $derived(companies.current);
	const company = $derived(companies.currentCompany);

	/** `path` is relative to `/c/<slug>/`; an item without one is not built yet and stays inert. */
	type Item = { label: string; path?: string; href?: '/components'; icon: Component };
	type Group = { heading: string; items: Item[] };

	const brain: Group = {
		heading: 'Brain',
		items: [
			{ label: 'Overview', path: '', icon: LayoutDashboard },
			{ label: 'Ask', path: 'ask', icon: MessageSquareText },
			{ label: 'Graph', path: 'graph', icon: Network },
			{ label: 'People', icon: Users },
			{ label: 'Systems', icon: Boxes },
			{ label: 'Sources', icon: BookOpen }
		]
	};
	const manage: Group = {
		heading: 'Company',
		items: [{ label: 'Settings', path: 'settings', icon: Settings }]
	};
	const build: Group = {
		heading: 'Build',
		items: [{ label: 'Components', href: '/components', icon: Palette }]
	};
	// The company groups only make sense inside a company; elsewhere the sidebar keeps Build.
	const groups = $derived(slug === null ? [build] : [brain, manage, build]);

	// Paths are this app's own routes; the cast to '/' only satisfies `resolve`'s route typing.
	const trim = (path: string) => path.replace(/\/+$/, '');
	function pathOf(item: Item): string | undefined {
		if (item.href) return item.href;
		if (item.path === undefined || slug === null) return undefined;
		return `/c/${slug}/${item.path}`;
	}
</script>

<nav class={['sidebar', { folded }]} aria-label="Main">
	{#if folded}
		<a class="brand mark" href={resolve('/')} onclick={onnavigate} aria-label="Citadel">C</a>
	{:else}
		<a class="brand" href={resolve('/')} onclick={onnavigate}>Citadel</a>
		{#if slug !== null && company}
			<div class="company">
				<p class="company-name">{company.name}</p>
				<p class="company-graph">brain_{company.slug}</p>
			</div>
		{/if}
	{/if}
	{#each groups as group (group.heading)}
		<div class="group">
			<h2 class={{ 'sr-only': folded }}>{group.heading}</h2>
			<ul>
				{#each group.items as item (item.label)}
					{@const path = pathOf(item)}
					{@const active = path !== undefined && trim(resolve(path as '/')) === trim(page.url.pathname)}
					<li>
						{#if path !== undefined && folded}
							<Tooltip text={item.label} side="right">
								{#snippet trigger(props)}
									<a
										{...props}
										href={resolve(path as '/')}
										class={['item', { active }]}
										aria-current={active ? 'page' : undefined}
										aria-label={item.label}
										onclick={onnavigate}
									>
										<item.icon aria-hidden="true" />
									</a>
								{/snippet}
							</Tooltip>
						{:else if path !== undefined}
							<a
								href={resolve(path as '/')}
								class={['item', { active }]}
								aria-current={active ? 'page' : undefined}
								onclick={onnavigate}
							>
								<item.icon aria-hidden="true" />
								{item.label}
							</a>
						{:else if folded}
							<Tooltip text="{item.label}: soon" side="right">
								{#snippet trigger(props)}
									<span {...props} class="item soon" role="img" aria-label="{item.label}, soon">
										<item.icon aria-hidden="true" />
									</span>
								{/snippet}
							</Tooltip>
						{:else}
							<span class="item soon" aria-disabled="true">
								<item.icon aria-hidden="true" />
								{item.label}
								<small>Soon</small>
							</span>
						{/if}
					</li>
				{/each}
			</ul>
		</div>
	{/each}
</nav>

<style>
	.sidebar {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		height: 100%;
		padding: var(--space-5) var(--space-3);
		background: var(--color-surface);
		border-right: var(--border-hair) solid var(--color-line);
		/* Folded, the 40px items overflow the 56px slot's padding and border by 1px: no sideways bar. */
		overflow-x: hidden;
		overflow-y: auto;
	}
	.brand {
		padding-inline: var(--space-3);
		color: var(--color-text);
		font-size: var(--text-xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
		letter-spacing: -0.01em;
		text-decoration: none;
	}
	.company {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-inline: var(--space-3);
		/* Hangs from the brand: the company head belongs to the brand above it. */
		margin-top: calc(-1 * var(--space-3));
	}
	.company-name {
		overflow: hidden;
		color: var(--color-text);
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.company-graph {
		overflow: hidden;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	h2 {
		padding-inline: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	ul {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--control-md);
		padding-inline: var(--space-3);
		border-radius: var(--radius-none);
		color: var(--color-text);
		font-weight: var(--weight-medium);
		text-decoration: none;
	}
	.item :global(svg) {
		width: 1.05rem;
		height: 1.05rem;
		flex: none;
	}
	a.item:hover {
		background: var(--color-surface-sunken);
	}
	.item.active,
	a.item.active:hover {
		background: var(--color-accent);
		color: var(--color-on-accent);
		font-weight: var(--weight-semibold);
	}
	.soon {
		color: var(--color-text-faint);
		cursor: default;
	}
	.soon small {
		margin-left: auto;
		font-size: var(--text-xs);
	}
	/* Folded: icons only, one column of 40px squares. */
	.folded {
		align-items: center;
		padding-inline: var(--space-2);
	}
	.folded .item {
		justify-content: center;
		width: var(--control-md);
		padding: 0;
	}
	.folded .group + .group {
		padding-top: var(--space-4);
		border-top: var(--border-hair) solid var(--color-line);
	}
	.mark {
		display: grid;
		place-items: center;
		width: var(--control-md);
		height: var(--control-md);
		padding: 0;
	}
</style>
