<!--
@component
Primary navigation. The current page is the solid ultramarine block: the one loud element in
the shell. Sections that are not built yet stay visible but inert, marked "Soon".
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
		Users
	} from '@lucide/svelte';
	import type { Component } from 'svelte';

	type Props = { onnavigate?: () => void };
	let { onnavigate }: Props = $props();

	type Item = { label: string; href?: '/' | '/components'; icon: Component };
	const groups: { heading: string; items: Item[] }[] = [
		{
			heading: 'Brain',
			items: [
				{ label: 'Overview', href: '/', icon: LayoutDashboard },
				{ label: 'Ask', icon: MessageSquareText },
				{ label: 'Graph', icon: Network },
				{ label: 'People', icon: Users },
				{ label: 'Systems', icon: Boxes },
				{ label: 'Sources', icon: BookOpen }
			]
		},
		{
			heading: 'Build',
			items: [{ label: 'Components', href: '/components', icon: Palette }]
		}
	];
</script>

<nav class="sidebar" aria-label="Main">
	<a class="brand" href={resolve('/')} onclick={onnavigate}>Citadel</a>
	{#each groups as group (group.heading)}
		<div class="group">
			<h2>{group.heading}</h2>
			<ul>
				{#each group.items as item (item.label)}
					{@const active = !!item.href && resolve(item.href) === page.url.pathname}
					<li>
						{#if item.href}
							<a
								href={resolve(item.href)}
								class={['item', { active }]}
								aria-current={active ? 'page' : undefined}
								onclick={onnavigate}
							>
								<item.icon aria-hidden="true" />
								{item.label}
							</a>
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
</style>
