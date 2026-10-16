<!--
@component
A single yes/no choice with its label beside it. A real checkbox underneath, so Space toggles it
and screen readers announce the state. Checked is an ink box with a check, so it never competes
with the one accent block on a view. Extra attributes (`name`, `required`) go to the input.
-->
<script lang="ts">
	import { Check } from '@lucide/svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';

	type Props = {
		label: string;
		checked: boolean;
		disabled?: boolean;
	} & Omit<HTMLInputAttributes, 'type' | 'checked' | 'disabled'>;

	let { label, checked = $bindable(false), disabled = false, ...rest }: Props = $props();
</script>

<label class={['check', { disabled }]}>
	<input type="checkbox" bind:checked {disabled} {...rest} />
	<span class="box" aria-hidden="true"><Check /></span>
	<span class="label">{label}</span>
</label>

<style>
	.check {
		position: relative;
		display: inline-flex;
		align-items: flex-start;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding-block: var(--space-1);
		max-width: 100%;
		font-size: var(--text-md);
		cursor: pointer;
	}
	input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		cursor: inherit;
	}
	.box {
		flex: none;
		display: grid;
		place-items: center;
		width: 1.125rem;
		height: 1.125rem;
		margin-top: 0.1875rem;
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-sm);
		color: transparent;
		transition: border-color var(--duration-fast) var(--ease-out);
	}
	.box :global(svg) {
		width: 0.8125rem;
		height: 0.8125rem;
		stroke-width: 3;
	}
	.check:hover:not(.disabled) .box {
		border-color: var(--color-text-muted);
	}
	input:checked + .box {
		background: var(--color-text);
		border-color: var(--color-text);
		color: var(--color-surface);
	}
	input:focus-visible + .box {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: var(--border-hair);
	}
	.label {
		min-width: 0;
		overflow-wrap: anywhere;
		line-height: var(--leading-ui);
		padding-top: 0.0625rem;
	}
	.disabled {
		cursor: not-allowed;
		color: var(--color-text-muted);
	}
	.disabled .box {
		background: var(--color-surface-sunken);
		border-color: var(--color-line);
	}
	.disabled input:checked + .box {
		background: var(--color-text-faint);
		border-color: var(--color-text-faint);
		color: var(--color-surface);
	}
</style>
