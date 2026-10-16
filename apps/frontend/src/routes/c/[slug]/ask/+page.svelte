<!--
@component
Ask: a conversation with one company's brain, with the agent's walk through the graph drawn beside
it (design direction D, "Watch it walk"). Left, the thread: questions, a live line while the agent
works, answers with citation chips. Right, the stage for the selected turn: the graph growing one
tool call at a time, and the steps with the rows each returned. Hovering a citation lights the
part of the walk that backs it; Replay shows a finished walk again. `?q=` (from the top bar's ask
field) asks once on arrival and is then removed from the address, so a reload does not ask again.
-->
<script lang="ts">
	import { LoaderCircle, RotateCcw, SquarePen } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { Banner, Button, GraphWalk, Input, WalkAnswer, WalkSteps } from '$lib';
	import { AskThread } from '$lib/ask.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import { askFieldOf } from '$lib/topbar';
	import { highlightFor, mergeWalk, stepSentence } from '$lib/walk';

	let { data } = $props();
	const companies = getCompanies();
	const company = $derived(companies.byslug(data.slug));
	const field = $derived(askFieldOf(company));

	// One conversation per company: switching company on the rail starts a fresh one.
	const thread = $derived(new AskThread(data.slug));
	$effect(() => {
		const t = thread;
		return () => t.dispose();
	});

	let question = $state('');
	let active = $state<number | null>(null);
	let pinned = $state<number | null>(null);
	let open = $state<string | null>(null);

	const turn = $derived(thread.turns[thread.selected]);
	const lit = $derived(active ?? pinned);
	const shown = $derived.by(() => {
		const steps = turn?.steps ?? [];
		const limit = thread.revealed;
		if (limit === null) return steps;
		return steps.filter((s) => s.n !== null && s.n <= limit);
	});
	const highlight = $derived.by(() => {
		const src = lit === null ? undefined : turn?.answer?.sources[lit - 1];
		return src ? highlightFor(src, turn!.steps) : null;
	});
	const cites = $derived.by(() => {
		const map = new Map<string, number[]>();
		turn?.answer?.sources.forEach((s, i) => map.set(s.uid, [...(map.get(s.uid) ?? []), i + 1]));
		return map;
	});
	const cited = $derived(new Set(turn?.answer?.sources.map((s) => s.uid) ?? []));
	const fresh = $derived.by(() => {
		if (turn?.status !== 'running') return null;
		// The first step is the whole picture so far: nothing to tell apart yet.
		const n = turn.steps.filter((s) => s.n !== null && s.status === 'done').at(-1)?.n ?? null;
		return n !== null && n > 1 ? n : null;
	});

	function live(t: NonNullable<typeof turn>): { line: string; meta: string } {
		const now = t.steps.findLast((s) => s.status === 'running');
		const graphSteps = t.steps.filter((s) => s.n !== null && s.status === 'done').length;
		const nodes = mergeWalk(t.steps).nodes.length;
		return {
			line: now ? `${stepSentence(now)}.` : graphSteps ? 'Deciding what to look up next.' : 'Reading the question.',
			meta: graphSteps ? `${graphSteps} ${graphSteps === 1 ? 'step' : 'steps'} · ${nodes} nodes so far` : ''
		};
	}

	function ask(text: string) {
		if (field.disabled || !text.trim()) return;
		if (thread.running) {
			question = text; // asked from the top bar mid-answer: keep it ready to send
			return;
		}
		active = pinned = null;
		open = null;
		void thread.ask(text);
		question = '';
	}

	function select(index: number) {
		thread.select(index);
		active = pinned = null;
		open = null;
	}

	function replay() {
		const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
		thread.replay(reduced);
	}

	// The top bar sends its question here as ?q=: ask it once, then drop it from the address.
	$effect(() => {
		const q = page.url.searchParams.get('q');
		if (!q) return;
		untrack(() => {
			// A real (replacing) navigation, so page.url loses q too; shallow replaceState keeps it.
			const url = new URL(page.url);
			url.searchParams.delete('q');
			void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
			ask(q);
		});
	});
</script>

<svelte:head><title>Ask · {company?.name ?? data.slug}</title></svelte:head>

<div class="ask">
	<section class="thread" aria-labelledby="ask-title">
		<header class="head">
			<h1 id="ask-title">Ask {company?.name ?? data.slug}</h1>
			{#if thread.turns.length}
				<Button size="sm" onclick={() => thread.reset()}><SquarePen aria-hidden="true" />New chat</Button>
			{/if}
		</header>

		{#if thread.turns.length === 0}
			<div class="intro">
				<p>
					Ask about people, systems or decisions. Each answer shows the walk the agent took through the graph and
					the rows behind every claim.
				</p>
				<ul class="examples" aria-label="Example questions">
					{#each thread.examples as example (example)}
						<li><Button size="sm" variant="ghost" disabled={field.disabled} onclick={() => ask(example)}>{example}</Button></li>
					{/each}
				</ul>
			</div>
		{/if}

		{#each thread.turns as t, i (i)}
			{@const selected = i === thread.selected}
			<article class={['turn', { selected }]} aria-current={selected && thread.turns.length > 1 ? 'true' : undefined}>
				<h2 class="question">{t.question}</h2>
				{#if t.status === 'running'}
					{@const now = live(t)}
					<div class="live" role="status">
						<p class="live-title"><LoaderCircle class="spin" aria-hidden="true" />Walking the graph</p>
						<p>{now.line}</p>
						{#if now.meta}<p class="meta">{now.meta}</p>{/if}
					</div>
				{:else if t.answer}
					<WalkAnswer
						answer={t.answer}
						active={selected ? lit : null}
						pinned={selected ? pinned : null}
						onactive={(n) => {
							if (!selected) select(i);
							active = n;
						}}
						onpin={(n) => {
							if (!selected) select(i);
							pinned = pinned === n ? null : n;
						}}
					/>
				{:else if t.error}
					<Banner tone="danger" title="This answer failed">{t.error}</Banner>
				{:else if t.status === 'stopped'}
					<p class="meta">You stopped this answer. The steps it took are kept on the right.</p>
				{/if}
				{#if !selected && t.steps.length}
					<div><Button size="sm" variant="ghost" onclick={() => select(i)}>Show its walk</Button></div>
				{/if}
			</article>
		{/each}

		<form
			class="composer"
			onsubmit={(e) => {
				e.preventDefault();
				ask(question);
			}}
		>
			<div class="field">
				<Input
					label="Your question"
					hideLabel
					placeholder={field.disabled ? field.placeholder : thread.turns.length ? 'Ask a follow-up' : field.placeholder}
					disabled={field.disabled}
					bind:value={question}
				/>
			</div>
			{#if thread.running}
				<Button onclick={() => thread.stop()}>Stop</Button>
			{:else}
				<Button type="submit" variant="primary" disabled={field.disabled || !question.trim()}>Ask</Button>
			{/if}
		</form>
	</section>

	<section class="stage" aria-labelledby="walk-title">
		<header class="head">
			<h2 id="walk-title">Graph walk</h2>
			{#if turn && thread.turns.length > 1}<p class="meta of">{turn.question}</p>{/if}
			<Button
				size="sm"
				disabled={!turn || turn.status === 'running' || !turn.steps.some((s) => s.n !== null)}
				onclick={replay}
			>
				<RotateCcw aria-hidden="true" />{thread.replaying ? 'Replaying' : 'Replay walk'}
			</Button>
		</header>
		<GraphWalk steps={shown} {highlight} {fresh} {cited} />
		{#if turn?.steps.length}
			<WalkSteps
				steps={shown}
				{open}
				ontoggle={(id) => (open = open === id ? null : id)}
				{cites}
				active={lit}
			/>
		{/if}
	</section>
</div>

<style>
	.ask {
		display: grid;
		grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
		gap: var(--space-6);
		align-items: start;
	}
	.thread {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-height: calc(100dvh - var(--topbar-height) - var(--space-12) - var(--space-6));
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
	}
	.head :global(.btn:last-child) {
		margin-left: auto;
	}
	h1 {
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	h2 {
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	.intro {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 66ch;
		color: var(--color-text-muted);
		font-size: var(--text-lg);
	}
	.examples {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.turn {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border-radius: var(--radius-md);
	}
	.turn.selected {
		background: var(--color-surface);
		outline: var(--border-hair) solid var(--color-line);
	}
	.question {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
		line-height: var(--leading-ui);
	}
	.live {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-lg);
	}
	.live-title {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
	}
	.live-title :global(svg) {
		width: 1rem;
		height: 1rem;
		color: var(--color-accent);
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.composer {
		position: sticky;
		bottom: 0;
		display: flex;
		gap: var(--space-2);
		margin-top: auto;
		padding-block: var(--space-3) var(--space-4);
		background: var(--color-ground);
	}
	.field {
		flex: 1;
		min-width: 0;
	}
	.stage {
		position: sticky;
		top: calc(var(--topbar-height) + var(--space-4));
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-height: calc(100dvh - var(--topbar-height) - var(--space-8));
		padding: var(--space-4);
		overflow-x: hidden;
		overflow-y: auto;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.of {
		overflow: hidden;
		flex: 1 1 10rem;
		min-width: 0;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	@media (max-width: 1100px) {
		.ask {
			grid-template-columns: minmax(0, 1fr);
		}
		.thread {
			min-height: 0;
		}
		.stage {
			position: static;
			max-height: none;
		}
	}
</style>
