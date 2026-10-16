<!--
@component
The company rail: one tile per company brain, so switching company is one click. The current
company is the ink tile (never accent: the active nav item owns the one accent block). A tile keeps
the section you are on (`/c/a/settings` -> `/c/b/settings`). Status is never colour alone: building
shows a spinner, failed and invalid an alert mark, an unreachable graph a cloud-off mark, and the
accessible name says the same in words. The tile list scrolls; the add tile stays pinned.
-->
<script lang="ts">
	import { CircleAlert, CloudOff, LoaderCircle, Plus } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import type { Component } from 'svelte';
	import Tooltip from '$lib/components/ui/Tooltip.svelte';
	import { monogram, sectionPath } from '$lib/companies';
	import type { Company, CompanyStatus } from '$lib/types';

	type Props = {
		companies: Company[];
		/** Slug of the current company, or null outside `/c/<slug>/`. */
		current: string | null;
		pathname: string;
		onnavigate?: () => void;
	};
	let { companies, current, pathname, onnavigate }: Props = $props();

	type Mark = { icon: Component; tone: 'warning' | 'danger' | 'muted'; words: string };
	const marks: Partial<Record<CompanyStatus, Mark>> = {
		building: { icon: LoaderCircle, tone: 'warning', words: 'building' },
		failed: { icon: CircleAlert, tone: 'danger', words: 'last build failed' },
		invalid: { icon: CircleAlert, tone: 'danger', words: 'config invalid' },
		unknown: { icon: CloudOff, tone: 'muted', words: 'graph unreachable' }
	};

	const newCompany = resolve('/new');
	const names = $derived(companies.map((c) => c.name));
	const label = (c: Company) =>
		`${c.name}, graph brain_${c.slug}${marks[c.status] ? `, ${marks[c.status]?.words}` : ''}`;

	// Bring the current tile into view when the current company changes (or its tile first
	// appears), but not on status updates, which would undo the user's own scrolling.
	let list: HTMLUListElement | undefined;
	let shown: string | null = null;
	$effect(() => {
		void companies.length;
		if (current === null || current === shown) return;
		const tile = list?.querySelector('[aria-current="true"]');
		if (!tile) return;
		tile.scrollIntoView({ block: 'nearest' });
		shown = current;
	});

	// Tooltip props carry their own click handler; keep it and add ours.
	function click(props: Record<string, unknown>) {
		return (e: MouseEvent) => {
			(props.onclick as ((e: MouseEvent) => void) | undefined)?.(e);
			onnavigate?.();
		};
	}
</script>

<nav class="rail" aria-label="Company brains">
	<h2>Brains</h2>
	<ul bind:this={list}>
		{#each companies as c (c.slug)}
			{@const mark = marks[c.status]}
			{@const isCurrent = c.slug === current}
			<li class={{ current: isCurrent }}>
				<Tooltip text={c.name} detail="brain_{c.slug}" side="right">
					{#snippet trigger(props)}
						<a
							{...props}
							class="tile"
							href={resolve(sectionPath(pathname, c.slug) as `/c/${string}`)}
							aria-current={isCurrent ? 'true' : undefined}
							aria-label={label(c)}
							onclick={click(props)}
						>
							<span class="mono" aria-hidden="true">{monogram(names, c.name)}</span>
							{#if mark}
								<span class={['badge', mark.tone]} aria-hidden="true">
									<mark.icon class={{ spin: c.status === 'building' }} />
								</span>
							{/if}
						</a>
					{/snippet}
				</Tooltip>
			</li>
		{/each}
	</ul>
	<div class="add">
		<Tooltip text="Add a company" side="right">
			{#snippet trigger(props)}
				<a {...props} class="tile new" href={newCompany} aria-label="Add a company" onclick={click(props)}>
					<Plus aria-hidden="true" />
				</a>
			{/snippet}
		</Tooltip>
	</div>
</nav>

<style>
	.rail {
		display: flex;
		flex-direction: column;
		flex: none;
		width: var(--rail-width);
		height: 100%;
		background: var(--color-ground);
		border-right: var(--border-hair) solid var(--color-line);
	}
	h2 {
		padding: var(--space-5) var(--space-3) var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	ul {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: var(--space-2);
		min-height: 0;
		margin: 0;
		padding: var(--space-2) 0;
		list-style: none;
		overflow-x: hidden;
		overflow-y: auto;
		/* A classic scrollbar would take 15px of the 72 and push the tiles off centre. */
		scrollbar-width: none;
	}
	li {
		position: relative;
		flex: none;
		padding-inline: var(--space-3);
	}
	/* The ink bar on the rail edge marks the current company beyond colour and weight. */
	li.current::before {
		content: '';
		position: absolute;
		inset: 0 auto 0 0;
		width: var(--rail-bar);
		background: var(--color-text);
	}
	.add {
		padding: var(--space-3);
		border-top: var(--border-hair) solid var(--color-line);
	}
	.tile {
		position: relative;
		display: grid;
		place-items: center;
		width: var(--control-lg);
		height: var(--control-lg);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		text-decoration: none;
		transition: background var(--duration-fast) var(--ease-out);
	}
	.tile:hover {
		background: var(--color-surface-sunken);
	}
	.mono {
		font-size: var(--rail-mark);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
		line-height: 1;
	}
	.current .tile,
	.current .tile:hover {
		border-color: var(--color-text);
		background: var(--color-text);
		color: var(--color-surface);
	}
	.current .mono {
		font-weight: var(--weight-black);
	}
	.new {
		border-style: dashed;
		color: var(--color-text-muted);
	}
	.new :global(svg) {
		width: 1.25rem;
		height: 1.25rem;
	}
	.badge {
		position: absolute;
		right: calc(-1 * var(--rail-badge-offset));
		bottom: calc(-1 * var(--rail-badge-offset));
		display: grid;
		place-items: center;
		width: var(--rail-badge);
		height: var(--rail-badge);
		border: var(--border-hair) solid currentColor;
		border-radius: var(--radius-full);
	}
	.badge :global(svg) {
		width: var(--rail-badge-icon);
		height: var(--rail-badge-icon);
	}
	.warning {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	.danger {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	.muted {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
	}
	.badge :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.badge :global(.spin) {
			animation: none;
		}
	}
</style>
