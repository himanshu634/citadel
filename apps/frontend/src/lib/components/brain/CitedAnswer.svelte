<!--
@component
An answer from the brain: the question, the answer text with citation chips, the graph path
and the numbered sources. Citations link to their source in the list below.
-->
<script lang="ts">
	import GraphPath from './GraphPath.svelte';
	import type { CitedAnswer } from '$lib/types';
	import type { Snippet } from 'svelte';

	type Props = { answer: CitedAnswer; actions?: Snippet };

	let { answer, actions }: Props = $props();
	const id = $props.id();
</script>

<article class="answer" aria-labelledby="{id}-q">
	<h3 id="{id}-q" class="question">{answer.question}</h3>
	<p class="text">
		{#each answer.parts as part, i (i)}
			{part.text}{#each part.cite ?? [] as n (n)}<a
					class="cite"
					href="#{id}-src-{n}"
					aria-label="Source {n}">{n}</a
				>{/each}
		{/each}
	</p>

	<div class="block">
		<h4>Graph path</h4>
		<GraphPath steps={answer.path} />
	</div>

	<div class="block">
		<h4>Sources</h4>
		<ol class="sources">
			{#each answer.sources as src, i (src.uid)}
				<li id="{id}-src-{i + 1}">
					<span class="n tabular">{i + 1}</span>
					<div>
						{#if src.url}
							<a href={src.url} target="_blank" rel="noreferrer">{src.title}</a>
						{:else}
							<span>{src.title}</span>
						{/if}
						<small>{src.meta}</small>
					</div>
				</li>
			{/each}
		</ol>
	</div>

	{#if actions}<div class="actions">{@render actions()}</div>{/if}
</article>

<style>
	.answer {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}
	.question {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.text {
		max-width: 66ch;
		font-size: var(--text-lg);
		line-height: var(--leading-body);
	}
	.cite {
		display: inline-block;
		min-width: 1.25rem;
		margin-left: 2px;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-accent-soft);
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		line-height: 1.5;
		text-align: center;
		text-decoration: none;
		vertical-align: 0.15em;
	}
	.cite:hover {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.block {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	h4 {
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		color: var(--color-text-muted);
	}
	.sources {
		display: flex;
		flex-direction: column;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.sources li {
		display: flex;
		gap: var(--space-3);
		padding-block: var(--space-2);
		border-top: var(--border-hair) solid var(--color-line);
		scroll-margin-top: calc(var(--topbar-height) + var(--space-4));
	}
	.sources li:first-child {
		border-top: 0;
		padding-top: 0;
	}
	.sources li:target {
		background: var(--color-accent-soft);
	}
	.n {
		flex: none;
		width: 1.25rem;
		color: var(--color-accent);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		line-height: 1.6rem;
	}
	.sources a,
	.sources span {
		color: var(--color-text);
		font-weight: var(--weight-medium);
	}
	.sources a {
		text-decoration-color: var(--color-line-strong);
	}
	.sources small {
		display: block;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
</style>
