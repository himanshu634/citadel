<!--
@component
Text field with a visible label. `hint` explains the field; `error` replaces the hint and marks
the field invalid. Put an icon in `leading` (for example a search glass).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';

	type Props = {
		label: string;
		/** Hide the label visually; it stays for screen readers. */
		hideLabel?: boolean;
		hint?: string;
		error?: string;
		value?: string;
		leading?: Snippet;
		size?: 'md' | 'lg';
	} & Omit<HTMLInputAttributes, 'size' | 'value'>;

	let {
		label,
		hideLabel = false,
		hint,
		error,
		value = $bindable(''),
		leading,
		size = 'md',
		id,
		...rest
	}: Props = $props();

	const autoId = $props.id();
	const inputId = $derived(id ?? autoId);
	const noteId = $derived(`${inputId}-note`);
</script>

<div class={['field', size, { invalid: !!error }]}>
	<label for={inputId} class={{ 'sr-only': hideLabel }}>{label}</label>
	<div class="control">
		{#if leading}<span class="leading" aria-hidden="true">{@render leading()}</span>{/if}
		<input
			id={inputId}
			bind:value
			aria-invalid={error ? true : undefined}
			aria-describedby={error || hint ? noteId : undefined}
			{...rest}
		/>
	</div>
	{#if error}
		<p id={noteId} class="note error">{error}</p>
	{:else if hint}
		<p id={noteId} class="note">{hint}</p>
	{/if}
</div>

<style>
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	label {
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.control {
		position: relative;
		display: flex;
		align-items: center;
	}
	.leading {
		position: absolute;
		left: var(--space-3);
		display: flex;
		color: var(--color-text-muted);
		pointer-events: none;
	}
	.leading :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	input {
		width: 100%;
		min-height: var(--control-md);
		padding-inline: var(--space-3);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		font-size: var(--text-md);
		transition: border-color var(--duration-fast) var(--ease-out);
	}
	.lg input {
		min-height: var(--control-lg);
		font-size: var(--text-lg);
	}
	.leading + input {
		padding-left: calc(var(--space-3) * 2 + 1rem);
	}
	input::placeholder {
		color: var(--color-text-faint);
	}
	input:hover:not(:disabled) {
		border-color: var(--color-text-muted);
	}
	input:focus-visible {
		outline: none;
		border-color: var(--color-focus);
		box-shadow: 0 0 0 1px var(--color-focus);
	}
	input:disabled {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	.invalid input {
		border-color: var(--color-danger);
	}
	.note {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.note.error {
		color: var(--color-danger);
	}
</style>
