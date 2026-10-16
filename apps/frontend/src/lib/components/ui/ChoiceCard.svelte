<!--
@component
One option in a set of cards, for choosing between a few things that need explaining (the data
permission). It is a real radio inside a label, so Tab, arrows and Space work as in any radio
group. Give every card in the set the same `name` and bind the same `group`. Wrap the set in a
`<fieldset>` with a `<legend>`. Selected = accent border, soft fill and a filled dot.
-->
<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';

	type Props = {
		name: string;
		value: string;
		/** The selected value of the whole set. */
		group: string;
		title: string;
		description: string;
	} & Omit<HTMLInputAttributes, 'name' | 'value' | 'group' | 'type' | 'title'>;

	let { name, value, group = $bindable(), title, description, disabled, ...rest }: Props = $props();

	const selected = $derived(group === value);
</script>

<label class={['card', { selected, disabled }]}>
	<input type="radio" {name} {value} {disabled} bind:group {...rest} />
	<span class="dot" aria-hidden="true"></span>
	<span class="text">
		<b>{title}</b>
		<small>{description}</small>
	</span>
</label>

<style>
	.card {
		position: relative;
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		min-width: 0;
		padding: var(--space-3) var(--space-4);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: border-color var(--duration-fast) var(--ease-out);
	}
	.card:hover:not(.disabled) {
		border-color: var(--color-text-muted);
	}
	.selected,
	.selected:hover:not(.disabled) {
		border-color: var(--color-accent);
		box-shadow: inset 0 0 0 var(--border-hair) var(--color-accent);
		background: var(--color-accent-soft);
	}
	.card:has(input:focus-visible) {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: var(--border-hair);
	}
	/* The real radio stays in the layout box so it keeps focus and keyboard behaviour. */
	input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		cursor: inherit;
	}
	.dot {
		flex: none;
		display: grid;
		place-items: center;
		width: 1.125rem;
		height: 1.125rem;
		margin-top: 0.125rem;
		border: var(--border-hair) solid var(--color-text-muted);
		border-radius: var(--radius-full);
		background: var(--color-surface);
	}
	.selected .dot {
		border-color: var(--color-accent);
	}
	.selected .dot::after {
		content: '';
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--color-accent);
	}
	.text {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	b {
		display: block;
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	small {
		display: block;
		margin-top: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.disabled {
		cursor: not-allowed;
		background: var(--color-surface-sunken);
		border-color: var(--color-line);
	}
	.disabled b {
		color: var(--color-text-muted);
	}
	.disabled .dot {
		border-color: var(--color-line-strong);
		background: var(--color-surface-sunken);
	}
	.disabled.selected {
		border-color: var(--color-line-strong);
		box-shadow: none;
	}
	.disabled.selected .dot::after {
		background: var(--color-text-muted);
	}
</style>
