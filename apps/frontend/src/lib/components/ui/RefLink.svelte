<!--
@component
A reference that opens where it lives, in a new tab: a PR or issue number, a commit, a document or
a file path (on GitHub, Linear or the source's own site). The text keeps the colour around it and
gets a quiet underline that turns accent on hover, so a sentence full of refs still reads calmly.
`code` sets it in mono on the sunken fill, for paths. `icon` is a small square with an arrow,
for rows whose text already selects something in the app (a table row on the Graph page). Never
put it inside a button. Get `href` from `src/lib/links.ts`, which only gives http(s) urls.
-->
<script lang="ts">
	import { ArrowUpRight } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { siteName } from '$lib/links';

	type Props = {
		href: string;
		/** Mono on the sunken fill: a file path or a SHA. */
		code?: boolean;
		/** Only the arrow; `label` says what it opens. */
		icon?: boolean;
		/** For `icon`: what the link opens ("PR #12"); "on GitHub" is added. */
		label?: string;
		children?: Snippet;
	};

	let { href, code = false, icon = false, label = '', children }: Props = $props();
	const site = $derived(siteName(href));
	const title = $derived(`Open ${label ? `${label} ` : ''}on ${site}`);
</script>

{#if icon}
	<a class="icon" {href} target="_blank" rel="noreferrer" aria-label={title} {title}><ArrowUpRight aria-hidden="true" /></a>
{:else}
	<a class={['ref', { code }]} {href} target="_blank" rel="noreferrer" title="Open on {site}">{@render children?.()}</a>
{/if}

<style>
	.ref {
		color: inherit;
		text-decoration-line: underline;
		text-decoration-color: var(--color-line-strong);
		text-decoration-thickness: var(--border-hair);
		text-underline-offset: 0.2em;
		overflow-wrap: anywhere;
		transition:
			color var(--duration-fast) var(--ease-out),
			text-decoration-color var(--duration-fast) var(--ease-out);
	}
	.ref:hover {
		color: var(--color-accent);
		text-decoration-color: currentColor;
	}
	.code {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono);
		font-size: 0.9em;
	}
	.icon {
		display: inline-grid;
		flex: none;
		place-items: center;
		width: var(--space-6);
		height: var(--space-6);
		border-radius: var(--radius-sm);
		color: var(--color-text-muted);
		transition:
			color var(--duration-fast) var(--ease-out),
			background var(--duration-fast) var(--ease-out);
	}
	.icon:hover {
		background: var(--color-accent-soft);
		color: var(--color-accent);
	}
	.icon :global(svg) {
		width: 1em;
		height: 1em;
	}
</style>
