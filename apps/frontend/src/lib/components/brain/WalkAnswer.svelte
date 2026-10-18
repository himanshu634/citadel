<!--
@component
An answer from the brain on the Ask page: the text with citation chips, then the numbered sources,
each saying which step of the walk found it. Hovering or focusing a chip or a source makes it the
active citation (`onactive`), which lights its path in `GraphWalk`; a click keeps it lit until
clicked again (`onpin`). With no answer it says why (refused, stopped, too many steps).
Only a small set of Markdown is understood, and never as HTML (`answerBlocks` in walk.ts). With
`refs`, `#12` and file paths in the text open on GitHub (or the item's own site) in a new tab.
Pass `reveal` for an answer that just arrived live: its blocks fade in one after another.
A source the Archivist loaded from before the window (`archived`) carries an "Archive · year"
badge. A source that is a Keeper claim (label `Claim`) carries an ink "Keeper" mark, so what the Keeper
holds is told apart from what the sources say; its chip says so to screen readers.
-->
<script lang="ts">
	import type { RefContext } from '$lib/links';
	import type { AskAnswer } from '$lib/types';
	import { answerBlocks, archiveBadge, sourceKind, type Inline } from '$lib/walk';
	import RefLink from '../ui/RefLink.svelte';

	type Props = {
		answer: AskAnswer;
		/** The active citation number. */
		active?: number | null;
		/** The pinned citation: stays active when the pointer leaves. */
		pinned?: number | null;
		onactive?: (n: number | null) => void;
		onpin?: (n: number) => void;
		/** Fade the blocks in, staggered (an answer that just arrived). */
		reveal?: boolean;
		/** What `#12` and paths in the text resolve against (`answerRefs`); none: they stay text. */
		refs?: RefContext;
	};

	let { answer, active = null, pinned = null, onactive, onpin, reveal = false, refs }: Props = $props();
	const id = $props.id();

	/** Each block starts this much after the one before, up to REVEAL_MAX blocks in. */
	const REVEAL_STAGGER_MS = 60;
	const REVEAL_MAX = 10;
	const delay = (i: number) => (reveal ? `${Math.min(i, REVEAL_MAX) * REVEAL_STAGGER_MS}ms` : undefined);

	const blocks = $derived(answer.text ? answerBlocks(answer.text, refs) : []);
	const NO_ANSWER: Record<string, string> = {
		refusal: 'Claude declined to answer this question.',
		stopped: 'You stopped this answer. The steps it took are kept above.',
		step_limit: 'It took too many steps without an answer. Try a narrower question.',
		max_tokens: 'The answer ran too long and was cut off. Try a narrower question.'
	};
	const why = $derived(NO_ANSWER[answer.stop ?? ''] ?? 'No answer came back. Try asking again.');
	const sourceTitle = (n: number) => answer.sources[n - 1]?.title ?? answer.sources[n - 1]?.uid ?? '';
	const isClaim = (n: number) => answer.sources[n - 1]?.label === 'Claim';
</script>

{#snippet runs(inlines: Inline[])}
	{#each inlines as part, i (i)}
		{#if part.kind === 'cite'}
			<button
				type="button"
				class={['cite', { on: active === part.n }]}
				aria-pressed={pinned === part.n}
				aria-label="Source {part.n}{isClaim(part.n) ? ', a Keeper claim' : ''}: {sourceTitle(part.n)}"
				aria-describedby="{id}-src-{part.n}"
				onmouseenter={() => onactive?.(part.n)}
				onmouseleave={() => onactive?.(null)}
				onfocus={() => onactive?.(part.n)}
				onblur={() => onactive?.(null)}
				onclick={() => onpin?.(part.n)}>{part.n}</button
			>
		{:else if part.kind === 'bold'}
			<strong>{part.text}</strong>
		{:else if part.kind === 'link'}
			<RefLink href={part.href} code={part.code}>{part.text}</RefLink>
		{:else if part.kind === 'code'}
			<code>{part.text}</code>
		{:else}
			{part.text}
		{/if}
	{/each}
{/snippet}

<div class={['answer', { reveal }]}>
	{#if answer.text}
		<div class="text">
			{#each blocks as block, i (i)}
				{#if block.kind === 'p'}
					<p class="block" style:animation-delay={delay(i)}>{@render runs(block.inlines)}</p>
				{:else}
					<svelte:element this={block.kind} class="block" style:animation-delay={delay(i)}>
						{#each block.items as item, j (j)}<li>{@render runs(item)}</li>{/each}
					</svelte:element>
				{/if}
			{/each}
		</div>
	{:else}
		<p class="why block">{why}</p>
	{/if}

	{#if answer.sources.length}
		<ol class="sources block" aria-label="Sources" style:animation-delay={delay(blocks.length)}>
			{#each answer.sources as src, i (i)}
				{@const n = i + 1}
				<li
					id="{id}-src-{n}"
					class={{ on: active === n }}
					onmouseenter={() => onactive?.(n)}
					onmouseleave={() => onactive?.(null)}
				>
					<span class="n tabular">{n}</span>
					<div>
						{#if src.label === 'Claim'}<span class="keeper">Keeper</span>{/if}
						{#if archiveBadge(src.archived)}<span class="archive">{archiveBadge(src.archived)}</span>{/if}
						{#if src.url}
							<a href={src.url} target="_blank" rel="noreferrer" onfocus={() => onactive?.(n)} onblur={() => onactive?.(null)}
								>{src.title ?? src.uid}</a
							>
						{:else}
							<span class="title">{src.title ?? src.uid}</span>
						{/if}
						<small>
							{sourceKind(src.label)}{#if src.step !== null}&ensp;·&ensp;found in step {src.step}{/if}
						</small>
					</div>
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.answer {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}
	.text {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 66ch;
		font-size: var(--text-lg);
		line-height: var(--leading-body);
	}
	.text :is(ul, ol) {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding-left: var(--space-6);
	}
	code {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono);
		font-size: 0.9em;
	}
	.why {
		color: var(--color-text-muted);
		font-size: var(--text-lg);
	}
	.cite {
		display: inline-block;
		min-width: 1.25rem;
		margin-left: 2px;
		padding: 0 var(--space-1);
		border: 0;
		border-radius: var(--radius-sm);
		background: var(--color-accent-soft);
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		line-height: 1.5;
		text-align: center;
		vertical-align: 0.15em;
		cursor: pointer;
	}
	.cite.on,
	.cite[aria-pressed='true'] {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.sources {
		display: flex;
		flex-direction: column;
		margin: 0;
		padding: var(--space-2) 0 0;
		border-top: var(--border-hair) solid var(--color-line);
		list-style: none;
	}
	.sources li {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-2);
		border-radius: var(--radius-md);
	}
	.sources li.on {
		background: var(--color-accent-soft);
	}
	.n {
		flex: none;
		width: 1rem;
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		line-height: 1.6rem;
	}
	.sources a,
	.title {
		color: var(--color-text);
		font-weight: var(--weight-medium);
		overflow-wrap: anywhere;
	}
	.sources a {
		text-decoration-color: var(--color-line-strong);
	}
	.keeper,
	.archive {
		display: inline-block;
		margin-right: var(--space-2);
		padding: 0 var(--space-1);
		border: var(--border-hair) solid var(--color-text);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		line-height: 1.4;
		vertical-align: 0.0625rem;
	}
	.archive {
		border-style: dashed;
		color: var(--color-text-muted);
		border-color: var(--color-line-strong);
	}
	small {
		display: block;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	/* `backwards` keeps a block hidden during its delay. */
	.reveal .block {
		animation: reveal var(--duration-base) var(--ease-out) backwards;
	}
	@keyframes reveal {
		from {
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.reveal .block {
			animation: none;
		}
	}
</style>
