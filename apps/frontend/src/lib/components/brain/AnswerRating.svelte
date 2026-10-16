<!--
@component
A thumbs up or down under an answer on the Ask page, saved on the answer's trace. A pressed thumb is
filled ink on a sunken fill, with `aria-pressed` and a line of words ("Marked right"); pressing it
again takes it back. After a thumbs down, an optional note says what was wrong: it becomes the
`why` of the draft eval case made from this answer. Saving and a failed save are said in words; a
failed save keeps the thumbs that was there before. Never accent: the answer's citations own it.
-->
<script lang="ts">
	import { CircleAlert, ThumbsDown, ThumbsUp } from '@lucide/svelte';
	import Button from '../ui/Button.svelte';
	import Input from '../ui/Input.svelte';
	import type { Rating } from '$lib/types';

	type Props = {
		rating: Rating | null;
		note?: string | null;
		status?: 'idle' | 'saving' | 'saved' | 'failed';
		/** A thumb pressed (or, with null, taken back). */
		onrate?: (rating: Rating | null) => void;
		/** The note sent with a thumbs down. */
		onnote?: (note: string) => void;
	};

	let { rating, note = null, status = 'idle', onrate, onnote }: Props = $props();

	let draft = $state('');
	const saving = $derived(status === 'saving');
	const said = $derived(
		status === 'saving'
			? 'Saving…'
			: rating === 'up'
				? 'Marked right.'
				: rating === 'down'
					? 'Marked wrong.'
					: 'Was this answer right?'
	);

	function press(next: Rating) {
		onrate?.(rating === next ? null : next);
	}
</script>

<div class="rating">
	<div class="row" role="group" aria-label="Rate this answer">
		<span class="said" aria-live="polite">{said}</span>
		<Button
			size="sm"
			variant="ghost"
			iconOnly
			label="Right answer"
			aria-pressed={rating === 'up'}
			disabled={saving}
			onclick={() => press('up')}><ThumbsUp aria-hidden="true" /></Button
		>
		<Button
			size="sm"
			variant="ghost"
			iconOnly
			label="Wrong answer"
			aria-pressed={rating === 'down'}
			disabled={saving}
			onclick={() => press('down')}><ThumbsDown aria-hidden="true" /></Button
		>
		{#if status === 'failed'}
			<span class="failed" role="alert"><CircleAlert aria-hidden="true" />Not saved. Try again.</span>
		{/if}
	</div>

	{#if rating === 'down'}
		{#if note}
			<p class="note">Your note: {note}</p>
		{:else}
			<form
				class="row"
				onsubmit={(e) => {
					e.preventDefault();
					if (draft.trim()) onnote?.(draft);
				}}
			>
				<div class="field">
					<Input
						label="What was wrong? (optional)"
						hideLabel
						placeholder="What was wrong? It goes into the test case for this question."
						disabled={saving}
						bind:value={draft}
					/>
				</div>
				<Button size="sm" type="submit" disabled={saving || !draft.trim()}>Send note</Button>
			</form>
		{/if}
	{/if}
</div>

<style>
	.rating {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
	}
	.said,
	.note {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.said {
		margin-right: var(--space-1);
	}
	.note {
		max-width: 66ch;
		overflow-wrap: anywhere;
	}
	.row :global(.btn[aria-pressed='true']) {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.row :global(.btn[aria-pressed='true'] svg) {
		fill: currentColor;
	}
	.failed {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.failed :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	.field {
		flex: 1 1 16rem;
		min-width: 0;
	}
</style>
