<!--
@component
The Claude model for the next Ask question (design direction P, "Chip in the composer"): a small
chip under the question field that opens the list of models, each with one line on what it is
good for and its price per token next to the cheapest (x1, x20, x40, x100). The default carries a
"Default" tag, a slow model a "Slow" tag. Locked (a padlock, and the reason in its name) while an
answer runs: one run per chat.
-->
<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { Check, ChevronUp, Cpu, Lock } from '@lucide/svelte';
	import type { ModelInfo } from '$lib/types';

	type Props = {
		models: ModelInfo[];
		/** The picked model's id. */
		selected: string | null;
		/** The server's default, tagged "Default". */
		defaultId?: string | null;
		/** While an answer runs. */
		disabled?: boolean;
		onpick: (id: string) => void;
	};

	let { models, selected, defaultId = null, disabled = false, onpick }: Props = $props();

	const current = $derived(models.find((m) => m.id === selected) ?? null);
	const label = $derived(
		disabled
			? `Model: ${current?.name ?? 'default'}, locked while this answer runs`
			: `Model for this question: ${current?.name ?? 'default'}`
	);
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger {disabled} aria-label={label} class="model-chip">
		{#if disabled}<Lock aria-hidden="true" />{:else}<Cpu aria-hidden="true" />{/if}
		<span>{current?.name ?? 'Default model'}</span>
		{#if !disabled}<ChevronUp aria-hidden="true" class="chev" />{/if}
	</DropdownMenu.Trigger>
	<DropdownMenu.Portal>
		<DropdownMenu.Content class="model-menu" side="top" align="start" sideOffset={8}>
			<DropdownMenu.RadioGroup value={selected ?? ''} onValueChange={(v) => v && onpick(v)}>
				<DropdownMenu.GroupHeading class="model-heading">Model for this question</DropdownMenu.GroupHeading>
				{#each models as m (m.id)}
					<DropdownMenu.RadioItem value={m.id} class="model-item">
						{#snippet children({ checked })}
							<span class="model-check" aria-hidden="true">{#if checked}<Check />{/if}</span>
							<span class="model-text">
								<span class="model-name">
									{m.name}
									{#if m.id === defaultId}<span class="tag">Default</span>{/if}
									{#if m.slow}<span class="tag slow">Slow</span>{/if}
								</span>
								<span class="model-blurb">{m.blurb}</span>
							</span>
							<span class="model-cost tabular" title="Price per token, compared with the cheapest model"
								>x{m.cost}</span
							>
						{/snippet}
					</DropdownMenu.RadioItem>
				{/each}
			</DropdownMenu.RadioGroup>
			<p class="model-foot">Price per token, compared with {models[0]?.name ?? 'the cheapest'}. Kept for your next questions.</p>
		</DropdownMenu.Content>
	</DropdownMenu.Portal>
</DropdownMenu.Root>

<style>
	:global(.model-chip) {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding: 0 var(--space-2) 0 var(--space-3);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	:global(.model-chip:hover:not(:disabled)) {
		background: var(--color-surface-sunken);
	}
	:global(.model-chip[data-state='open']) {
		border-color: var(--color-accent);
		background: var(--color-accent-soft);
	}
	:global(.model-chip:disabled) {
		border-style: dashed;
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	:global(.model-chip:focus-visible) {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: 2px;
	}
	:global(.model-chip svg) {
		width: 0.875rem;
		height: 0.875rem;
		flex: none;
	}
	:global(.model-menu) {
		z-index: 50;
		width: min(24rem, calc(100vw - var(--space-8)));
		padding: var(--space-1);
		background: var(--color-surface-raised);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-overlay);
	}
	:global(.model-menu:focus-visible) {
		outline: none;
	}
	:global(.model-heading) {
		padding: var(--space-2) var(--space-3) var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	:global(.model-item) {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3) var(--space-2) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
		outline: none;
	}
	:global(.model-item[data-highlighted]) {
		background: var(--color-surface-sunken);
	}
	:global(.model-item[data-state='checked']) {
		background: var(--color-accent-soft);
	}
	.model-check {
		display: grid;
		place-items: center;
		width: 1rem;
		padding-top: 2px;
		color: var(--color-accent);
		flex: none;
	}
	.model-check :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	.model-text {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}
	.model-name {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.model-blurb {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.model-cost {
		padding-top: 2px;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.tag {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-body);
	}
	.tag.slow {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	.model-foot {
		margin: var(--space-1) var(--space-2) 0;
		padding: var(--space-2) var(--space-1) var(--space-1);
		border-top: var(--border-hair) solid var(--color-line);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
</style>
