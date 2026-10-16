<!--
@component
Primary navigation. The current page is the solid ultramarine block: the one loud element in
the shell. Sections that are not built yet stay visible but inert, marked "Soon". `folded` shows
the icons only (`--sidebar-folded` wide), each named by a tooltip. Open and folded are one markup:
AppShell animates the slot's width, the labels fade (out at once, in once there is room) and are
clipped, and no icon or row moves. Each link carries its name in `aria-label`, so a folded item
keeps it. `--fold-motion` (1, or 0 from AppShell before its first paint) turns the fades off.
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
	<!-- Folded, the brand keeps its C: the rest of the word fades into the clipped edge. -->
	<a class="brand" href={resolve('/')} onclick={onnavigate}>C<span class="label">itadel</span></a>
	{#if slug !== null && company}
		<div class="company" aria-hidden={folded}>
			<p class="company-name">{company.name}</p>
			<p class="company-graph">brain_{company.slug}</p>
		</div>
	{/if}
	{#each groups as group (group.heading)}
		<div class="group">
			<h2><span class="label">{group.heading}</span></h2>
			<ul>
				{#each group.items as item (item.label)}
					{@const path = pathOf(item)}
					{@const active = path !== undefined && trim(resolve(path as '/')) === trim(page.url.pathname)}
					<li>
						{#if path !== undefined}
							<Tooltip text={item.label} side="right" disabled={!folded}>
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
										<span class="label">{item.label}</span>
									</a>
								{/snippet}
							</Tooltip>
						{:else}
							<Tooltip text="{item.label}: soon" side="right" disabled={!folded}>
								{#snippet trigger(props)}
									<span {...props} class="item soon" aria-disabled="true">
										<item.icon aria-hidden="true" />
										<span class="label">{item.label} <small>Soon</small></span>
									</span>
								{/snippet}
							</Tooltip>
						{/if}
					</li>
				{/each}
			</ul>
		</div>
	{/each}
</nav>

<style>
	.sidebar {
		/* Labels fade out at once and fade in once the slot has mostly opened. */
		--fold-fade: calc(var(--duration-fast) * var(--fold-motion, 1));
		--fold-delay: calc((var(--duration-base) - var(--duration-fast)) * var(--fold-motion, 1));
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		height: 100%;
		/* The same in both states, so the icons keep their place while the width changes. */
		padding: var(--space-5) var(--space-2);
		background: var(--color-surface);
		border-right: var(--border-hair) solid var(--color-line);
		overflow-x: hidden;
		overflow-y: auto;
	}
	.folded {
		--fold-delay: 0s;
	}
	.label {
		white-space: nowrap;
		transition: opacity var(--fold-fade) var(--ease-out) var(--fold-delay);
	}
	.folded .label {
		opacity: 0;
	}
	.brand {
		padding-inline: var(--space-3);
		color: var(--color-text);
		font-size: var(--text-xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
		letter-spacing: -0.01em;
		text-decoration: none;
		white-space: nowrap;
	}
	.company {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-inline: var(--space-3);
		/* Hangs from the brand: the company head belongs to the brand above it. */
		margin-top: calc(-1 * var(--space-3));
		transition: opacity var(--fold-fade) var(--ease-out) var(--fold-delay);
	}
	.folded .company {
		opacity: 0;
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
	/* Folded, a heading keeps its row and becomes the hairline between groups. */
	h2 {
		position: relative;
		padding-inline: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.group + .group h2::after {
		content: '';
		position: absolute;
		inset-inline: 0;
		top: 50%;
		border-top: var(--border-hair) solid var(--color-line);
		opacity: 0;
		transition: opacity var(--fold-fade) var(--ease-out);
	}
	.folded .group + .group h2::after {
		opacity: 1;
		transition-delay: var(--fold-fade);
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
		/* Clips the label at the block's edge while the slot narrows. */
		overflow: hidden;
		border-radius: var(--radius-none);
		color: var(--color-text);
		font-weight: var(--weight-medium);
		text-decoration: none;
		transition:
			background-color var(--duration-fast) var(--ease-out),
			color var(--duration-fast) var(--ease-out),
			transform var(--duration-fast) var(--ease-out);
	}
	.item :global(svg) {
		width: 1.05rem;
		height: 1.05rem;
		flex: none;
		transition: transform var(--duration-fast) var(--ease-out);
	}
	.item .label {
		display: flex;
		flex: 1 0 auto;
		align-items: center;
		gap: var(--space-2);
	}
	a.item:hover {
		background: var(--color-surface-sunken);
	}
	a.item:hover :global(svg) {
		transform: scale(1.08);
	}
	a.item:active {
		transform: scale(0.97);
	}
	.item.active,
	a.item.active:hover {
		background: var(--color-accent);
		color: var(--color-on-accent);
		font-weight: var(--weight-semibold);
	}
	a.item.active:hover :global(svg) {
		transform: none;
	}
	.soon {
		color: var(--color-text-faint);
		cursor: default;
	}
	.soon small {
		margin-left: auto;
		font-size: var(--text-xs);
	}
	@media (prefers-reduced-motion: reduce) {
		.sidebar {
			--fold-fade: 0s;
			--fold-delay: 0s;
		}
		a.item:hover :global(svg),
		a.item:active {
			transform: none;
		}
	}
</style>
