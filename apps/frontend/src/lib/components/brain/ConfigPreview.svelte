<!--
@component
The `companies/<slug>.yaml` the server will write, as text. Top-level keys in `highlight` (the
ones the current step adds) are marked with a bar and a tinted fill, and a line says so, so the
mark is not colour alone. `stale` says the text is the last valid version because the form has
errors right now. The text comes from the validate endpoint and is shown as it came; nothing here
formats or edits it.
-->
<script lang="ts">
	import { splitYamlBlocks } from '$lib/onboarding';

	type Props = {
		yaml: string;
		/** Top-level keys to mark. */
		highlight: string[];
		/** The form has errors: this is the last version that was valid. */
		stale?: boolean;
	};

	let { yaml, highlight, stale = false }: Props = $props();

	const blocks = $derived(splitYamlBlocks(yaml));
	const slug = $derived(blocks.find((b) => b.key === 'slug')?.text.replace(/^slug:\s*/, '').trim());
	const marked = $derived(blocks.some((b) => highlight.includes(b.key)));
</script>

<aside class="preview" aria-label="Config preview">
	<div class="head">
		<h2>companies/{slug || '<slug>'}.yaml</h2>
		<p class="hint">Saved when you start the build.</p>
	</div>
	{#if blocks.length > 0}
		<pre>{#each blocks as block (block.key)}<span class={['block', { new: highlight.includes(block.key) }]}>{block.text}</span>{/each}</pre>
		{#if marked}<p class="legend">Marked lines are added by this step.</p>{/if}
	{:else}
		<p class="empty">The file appears here as you fill in the form.</p>
	{/if}
	{#if stale && blocks.length > 0}
		<p class="stale" role="status">Showing the last valid version. Fix the errors to update it.</p>
	{/if}
</aside>

<style>
	.preview {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
		padding: var(--space-5);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	h2 {
		font-family: var(--font-mono);
		font-size: var(--text-md);
		font-weight: var(--weight-medium);
		overflow-wrap: anywhere;
	}
	.hint,
	.legend,
	.stale,
	.empty {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.stale {
		color: var(--color-warning);
	}
	pre {
		padding: var(--space-3) 0;
		background: var(--color-surface-sunken);
		border-radius: var(--radius-md);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		line-height: 1.65;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		color: var(--color-text-muted);
	}
	.block {
		display: block;
		padding-inline: var(--space-3);
		border-left: 3px solid transparent;
	}
	.block.new {
		background: var(--color-accent-soft);
		border-left-color: var(--color-accent);
		color: var(--color-text);
	}
</style>
