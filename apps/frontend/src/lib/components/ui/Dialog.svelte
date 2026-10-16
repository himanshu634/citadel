<!--
@component
Modal dialog on bits-ui: focus is trapped, Escape closes, focus returns to the trigger.
`title` is required. `footer` holds the actions; put the confirming action last. `initialFocus`
is a selector inside the dialog to focus on open (default: the panel itself). `placement="top"`
pins the panel's top edge, for a dialog whose body grows while you type (it would jump if centred).
-->
<script lang="ts">
	import { Dialog } from 'bits-ui';
	import { X } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	type Props = {
		open?: boolean;
		title: string;
		description?: string;
		trigger?: Snippet<[Record<string, unknown>]>;
		children?: Snippet;
		footer?: Snippet;
		initialFocus?: string;
		placement?: 'center' | 'top';
	};

	let {
		open = $bindable(false),
		title,
		description,
		trigger,
		children,
		footer,
		initialFocus,
		placement = 'center'
	}: Props = $props();

	let content: HTMLElement | null = $state(null);
	function focusFirst(event: Event) {
		const target = initialFocus ? content?.querySelector<HTMLElement>(initialFocus) : null;
		if (!target) return;
		event.preventDefault();
		target.focus();
	}
</script>

<Dialog.Root bind:open>
	{#if trigger}
		<Dialog.Trigger>
			{#snippet child({ props })}
				{@render trigger(props)}
			{/snippet}
		</Dialog.Trigger>
	{/if}
	<Dialog.Portal>
		<Dialog.Overlay class="dialog-scrim" />
		<Dialog.Content class="dialog {placement}" bind:ref={content} onOpenAutoFocus={focusFirst}>
			<header class="dialog-head">
				<Dialog.Title class="dialog-title">{title}</Dialog.Title>
				<Dialog.Close class="dialog-close" aria-label="Close">
					<X aria-hidden="true" />
				</Dialog.Close>
			</header>
			{#if description}
				<Dialog.Description class="dialog-description">{description}</Dialog.Description>
			{/if}
			{#if children}<div class="dialog-body">{@render children()}</div>{/if}
			{#if footer}<footer class="dialog-foot">{@render footer()}</footer>{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>

<style>
	/* The panel takes focus on open; its items show focus, so the panel itself needs no ring. */
	:global(.dialog:focus-visible) {
		outline: none;
	}
	:global(.dialog-scrim) {
		position: fixed;
		inset: 0;
		z-index: 40;
		background: var(--color-scrim);
	}
	:global(.dialog) {
		position: fixed;
		z-index: 41;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(32rem, calc(100vw - 2 * var(--space-4)));
		max-height: calc(100dvh - 2 * var(--space-8));
		overflow: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-5);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	:global(.dialog.top) {
		top: min(12vh, var(--space-12) * 2);
		transform: translateX(-50%);
		max-height: calc(100dvh - min(12vh, var(--space-12) * 2) - var(--space-8));
	}
	:global(.dialog-head) {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
	}
	:global(.dialog-title) {
		font-size: var(--text-xl);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	:global(.dialog-close) {
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		margin: calc(var(--space-1) * -1);
		border: 0;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
	}
	:global(.dialog-close:hover) {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	:global(.dialog-close svg) {
		width: 1.1rem;
		height: 1.1rem;
	}
	:global(.dialog-description) {
		color: var(--color-text-muted);
	}
	:global(.dialog-foot) {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-2);
		padding-top: var(--space-2);
	}
</style>
