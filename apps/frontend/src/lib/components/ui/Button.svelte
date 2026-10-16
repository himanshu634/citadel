<!--
@component
One button for every action. `primary` is the one main action on a view; use it once.
Pass `href` to render a link that looks like a button. Icon-only buttons need `label`.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';

	type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
	type Size = 'sm' | 'md' | 'lg';

	type Props = {
		variant?: Variant;
		size?: Size;
		/** Accessible name; required when the button shows only an icon. */
		label?: string;
		iconOnly?: boolean;
		href?: string;
		loading?: boolean;
		children?: Snippet;
	} & Omit<HTMLButtonAttributes, 'children'> &
		Omit<HTMLAnchorAttributes, 'children'>;

	let {
		variant = 'secondary',
		size = 'md',
		label,
		iconOnly = false,
		href,
		loading = false,
		disabled,
		type = 'button',
		class: className,
		children,
		...rest
	}: Props = $props();

	const classes = $derived(['btn', variant, size, { 'icon-only': iconOnly, loading }, className]);
</script>

{#if href && !disabled}
	<a {href} class={classes} aria-label={label} {...rest as HTMLAnchorAttributes}>
		{@render children?.()}
	</a>
{:else}
	<button
		{type}
		class={classes}
		aria-label={label}
		disabled={disabled || loading}
		aria-busy={loading || undefined}
		{...rest as HTMLButtonAttributes}
	>
		{@render children?.()}
	</button>
{/if}

<style>
	.btn {
		--h: var(--control-md);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-height: var(--h);
		padding-inline: var(--space-4);
		border: var(--border-hair) solid transparent;
		border-radius: var(--radius-md);
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		line-height: 1;
		text-decoration: none;
		white-space: nowrap;
		cursor: pointer;
		transition:
			background-color var(--duration-fast) var(--ease-out),
			border-color var(--duration-fast) var(--ease-out),
			color var(--duration-fast) var(--ease-out);
	}
	.btn :global(svg) {
		width: 1.1em;
		height: 1.1em;
		flex: none;
	}
	.sm {
		--h: var(--control-sm);
		padding-inline: var(--space-3);
		font-size: var(--text-sm);
	}
	.lg {
		--h: var(--control-lg);
		padding-inline: var(--space-5);
		font-size: var(--text-lg);
	}
	.icon-only {
		width: var(--h);
		padding-inline: 0;
	}

	.primary {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.primary:hover {
		background: var(--color-accent-hover);
	}
	.secondary {
		background: var(--color-surface);
		border-color: var(--color-line-strong);
		color: var(--color-text);
	}
	.secondary:hover {
		border-color: var(--color-text-muted);
	}
	.ghost {
		background: transparent;
		color: var(--color-text);
	}
	.ghost:hover {
		background: var(--color-surface-sunken);
	}
	.danger {
		background: var(--color-surface);
		border-color: var(--color-danger);
		color: var(--color-danger);
	}
	.danger:hover {
		background: var(--color-danger-soft);
	}

	.btn:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
	.loading {
		cursor: progress;
	}
</style>
