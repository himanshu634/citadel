<!--
@component
A list of short values typed into one field (path globs, logins, aliases). Enter or a comma adds
what is typed (a comma inside `{}` stays in the tag, so `*.{ts,tsx}` is one glob); pasting "a, b" adds both; Backspace on an empty field removes the last tag; text
left in the field is added when focus leaves. Each tag has a button named "Remove <tag>". The rules
(trim, no empty, no new duplicates) are in `$lib/tags`; duplicates already in `values` are kept and shown. `mono` sets tags and text in the mono face for
paths and ids.
-->
<script lang="ts">
	import { X } from '@lucide/svelte';
	import { addTags, hasSeparator, inOpenBrace, removeAt } from '$lib/tags';

	type Props = {
		label: string;
		values: string[];
		placeholder?: string;
		mono?: boolean;
		hint?: string;
		error?: string;
		disabled?: boolean;
		id?: string;
	};

	let {
		label,
		values = $bindable([]),
		placeholder,
		mono = false,
		hint,
		error,
		disabled = false,
		id
	}: Props = $props();

	const autoId = $props.id();
	const inputId = $derived(id ?? autoId);
	const noteId = $derived(`${inputId}-note`);

	let text = $state('');
	let input: HTMLInputElement | undefined = $state();

	function commit() {
		values = addTags(values, text);
		text = '';
	}

	function remove(index: number) {
		values = removeAt(values, index);
		input?.focus();
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.isComposing) return;
		// A comma inside an open `{` belongs to a brace glob (`*.{ts,tsx}`): let it be typed.
		if (e.key === ',' && inOpenBrace(text)) return;
		if (e.key === 'Enter' || e.key === ',') {
			// Enter must not submit the surrounding form while the user is still typing tags.
			e.preventDefault();
			commit();
		} else if (e.key === 'Backspace' && text === '' && values.length > 0) {
			values = values.slice(0, -1);
		}
	}

	// A paste (or an IME) can put a separator inside the text without a key press.
	function oninput() {
		if (hasSeparator(text)) commit();
	}
</script>

<div class={['field', { invalid: !!error, disabled, mono }]}>
	<label for={inputId}>{label}</label>
	<div class="control">
		{#if values.length > 0}
			<ul class="tags" aria-label="{label}, {values.length} added">
				<!-- Keyed by position: a hand-edited config can hold the same tag twice. -->
				{#each values as tag, i (i)}
					<li class="tag">
						<span class="tag-text">{tag}</span>
						<button type="button" {disabled} aria-label="Remove {tag}" onclick={() => remove(i)}>
							<X aria-hidden="true" />
						</button>
					</li>
				{/each}
			</ul>
		{/if}
		<input
			id={inputId}
			bind:this={input}
			bind:value={text}
			{placeholder}
			{disabled}
			autocomplete="off"
			spellcheck="false"
			aria-invalid={error ? true : undefined}
			aria-describedby={error || hint ? noteId : undefined}
			{onkeydown}
			{oninput}
			onblur={commit}
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
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		min-height: var(--control-md);
		padding: var(--space-1) var(--space-2);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		transition: border-color var(--duration-fast) var(--ease-out);
	}
	.control:hover:not(:has(input:disabled)) {
		border-color: var(--color-text-muted);
	}
	.control:has(input:focus-visible) {
		border-color: var(--color-focus);
		box-shadow: 0 0 0 1px var(--color-focus);
	}
	.invalid .control {
		border-color: var(--color-danger);
	}
	.tags {
		display: contents;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.tag {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-width: 0;
		max-width: 100%;
		padding: 0 var(--space-1) 0 var(--space-2);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
	.mono .tag,
	.mono input {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.tag-text {
		min-width: 0;
		overflow-wrap: anywhere;
		line-height: var(--leading-ui);
	}
	.tag button {
		display: grid;
		place-items: center;
		flex: none;
		width: var(--space-6);
		height: var(--space-6);
		padding: 0;
		background: transparent;
		border: 0;
		border-radius: var(--radius-sm);
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.tag button:hover:not(:disabled) {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.tag button:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: calc(var(--border-hair) * -1);
	}
	.tag button :global(svg) {
		width: 0.875rem;
		height: 0.875rem;
	}
	input {
		flex: 1 1 8rem;
		min-width: 0;
		min-height: var(--control-sm);
		padding: 0 var(--space-1);
		background: transparent;
		border: 0;
		font-size: var(--text-md);
	}
	input:focus-visible {
		outline: none;
	}
	input::placeholder {
		color: var(--color-text-faint);
	}
	.disabled .control {
		background: var(--color-surface-sunken);
		cursor: not-allowed;
	}
	.disabled input,
	.disabled .tag {
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	.disabled .tag {
		background: var(--color-surface-sunken);
		border-color: var(--color-line);
	}
	.disabled .tag button {
		cursor: not-allowed;
	}
	.note {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.note.error {
		color: var(--color-danger);
	}
</style>
