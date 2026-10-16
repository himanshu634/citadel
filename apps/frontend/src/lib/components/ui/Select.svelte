<!--
@component
Pick one of a short list (bits-ui Select: arrows, Home/End, typeahead, Enter or Space to choose,
Escape to close). The label stays visible above the field. `hint` explains it; `error` replaces
the hint and marks the field invalid. For two or three options that need explaining, use
`ChoiceCard` instead. A long option label wraps in the list and truncates on the closed field.
-->
<script lang="ts">
	import { Select } from 'bits-ui';
	import { Check, ChevronDown } from '@lucide/svelte';

	type Option = { value: string; label: string };

	type Props = {
		label: string;
		value: string;
		options: Option[];
		hint?: string;
		error?: string;
		/** Shown on the closed field while `value` matches no option. */
		placeholder?: string;
		disabled?: boolean;
		id?: string;
	};

	let {
		label,
		value = $bindable(''),
		options,
		hint,
		error,
		placeholder = 'Choose one',
		disabled = false,
		id
	}: Props = $props();

	const autoId = $props.id();
	const triggerId = $derived(id ?? autoId);
	const labelId = $derived(`${triggerId}-label`);
	const valueId = $derived(`${triggerId}-value`);
	const noteId = $derived(`${triggerId}-note`);
	const chosen = $derived(options.find((o) => o.value === value));
</script>

<div class={['field', { invalid: !!error, disabled }]}>
	<span id={labelId} class="label">{label}</span>
	<Select.Root type="single" bind:value items={options} {disabled}>
		<Select.Trigger
			id={triggerId}
			class="trigger"
			aria-labelledby="{labelId} {valueId}"
			aria-invalid={error ? true : undefined}
			aria-describedby={error || hint ? noteId : undefined}
		>
			<span id={valueId} class={['value', { placeholder: !chosen }]}>
				{chosen ? chosen.label : placeholder}
			</span>
			<ChevronDown aria-hidden="true" />
		</Select.Trigger>
		<Select.Portal>
			<Select.Content class="select-panel" sideOffset={4} align="start" collisionPadding={16}>
				<Select.Viewport>
					{#each options as option (option.value)}
						<Select.Item value={option.value} label={option.label} class="select-item">
							{#snippet children({ selected })}
								<span class="select-check" aria-hidden="true">
									{#if selected}<Check />{/if}
								</span>
								<span class="select-label">{option.label}</span>
							{/snippet}
						</Select.Item>
					{/each}
				</Select.Viewport>
			</Select.Content>
		</Select.Portal>
	</Select.Root>
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
	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.field :global(.trigger) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		width: 100%;
		min-height: var(--control-md);
		padding-inline: var(--space-3);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		font-size: var(--text-md);
		text-align: left;
		cursor: pointer;
		transition: border-color var(--duration-fast) var(--ease-out);
	}
	.field :global(.trigger svg) {
		flex: none;
		width: 1rem;
		height: 1rem;
		color: var(--color-text-muted);
	}
	.field :global(.trigger:hover:not(:disabled)) {
		border-color: var(--color-text-muted);
	}
	.field :global(.trigger:focus-visible) {
		outline: none;
		border-color: var(--color-focus);
		box-shadow: 0 0 0 1px var(--color-focus);
	}
	.invalid :global(.trigger) {
		border-color: var(--color-danger);
	}
	.field :global(.trigger:disabled) {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	.value {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.placeholder {
		color: var(--color-text-faint);
	}
	.note {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.note.error {
		color: var(--color-danger);
	}

	/* The list renders in a portal, so its styles are global and namespaced by class. */
	:global(.select-panel) {
		z-index: 50;
		min-width: var(--bits-select-anchor-width);
		max-width: min(100vw - var(--space-8), 28rem);
		max-height: min(var(--bits-select-content-available-height), 20rem);
		overflow-y: auto;
		padding: var(--space-1);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	:global(.select-panel:focus-visible) {
		outline: none;
	}
	:global(.select-item) {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		min-height: var(--control-md);
		padding: var(--space-2) var(--space-3) var(--space-2) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
		outline: none;
	}
	:global(.select-item[data-highlighted]) {
		background: var(--color-accent-soft);
	}
	:global(.select-item[data-selected]) {
		font-weight: var(--weight-semibold);
	}
	:global(.select-item[data-disabled]) {
		color: var(--color-text-faint);
		cursor: not-allowed;
	}
	:global(.select-check) {
		display: grid;
		place-items: center;
		flex: none;
		width: 1rem;
		height: 1.25rem;
		color: var(--color-accent);
	}
	:global(.select-check svg) {
		width: 1rem;
		height: 1rem;
	}
	:global(.select-label) {
		min-width: 0;
		overflow-wrap: anywhere;
		line-height: var(--leading-ui);
	}
</style>
