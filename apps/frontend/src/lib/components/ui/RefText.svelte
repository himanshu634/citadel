<!--
@component
Text with its references linked: the runs from `textRuns` or `labelRuns` (src/lib/links.ts), each
run with an `href` as a `RefLink`, the rest as plain text. Inline, so it sits in any sentence; never
inside a button. Paths are set in mono (`code`) when `codePaths` is on.
-->
<script lang="ts">
	import type { TextRun } from '$lib/links';
	import RefLink from './RefLink.svelte';

	type Props = { runs: TextRun[]; codePaths?: boolean };

	let { runs, codePaths = false }: Props = $props();
	const isPath = (t: string) => t.includes('/') && !t.includes('#');
</script>

{#each runs as run, i (i)}{#if run.href}<RefLink href={run.href} code={codePaths && isPath(run.text)}>{run.text}</RefLink
		>{:else}{run.text}{/if}{/each}
