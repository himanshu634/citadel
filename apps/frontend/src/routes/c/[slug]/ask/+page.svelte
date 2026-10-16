<!--
@component
Ask: a conversation with one company's brain, one lane per question (design direction J + L).
Each lane (`AskLane`) holds the conversation on the left and that question's own walk through the
graph on the right, on one scroll. The line between the two columns is a splitter: drag it, or
use its keys, to resize the walk column or fold it to a strip (kept in this browser,
`citadel-ask-walk`); the button at the top of the walk column folds and opens it too. A new
question scrolls to the top and the view stays there while the answer grows; "Jump to latest"
appears when the end is out of view. The composer sits under the chat column. At 1100px and
below everything is one column with each walk under its conversation. `?q=` (from the top bar's
ask field) asks once on arrival and is then removed from the address, so a reload does not ask
again.
-->
<script lang="ts">
	import { ArrowDown, PanelRightClose, PanelRightOpen, SquarePen } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { tick, untrack } from 'svelte';
	import type { Attachment } from 'svelte/attachments';
	import { prefersReducedMotion } from 'svelte/motion';
	import { MediaQuery } from 'svelte/reactivity';
	import { Button, Input } from '$lib';
	import { AskThread } from '$lib/ask.svelte';
	import AskLane from '$lib/components/brain/AskLane.svelte';
	import Splitter from '$lib/components/ui/Splitter.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import { WALK_LIMITS, clampSize, readSplit } from '$lib/splitter';
	import { askFieldOf } from '$lib/topbar';

	let { data } = $props();
	const companies = getCompanies();
	const company = $derived(companies.byslug(data.slug));
	const field = $derived(askFieldOf(company));
	const name = $derived(company?.name ?? data.slug);

	// One conversation per company: switching company on the rail starts a fresh one.
	const thread = $derived(new AskThread(data.slug));
	$effect(() => {
		const t = thread;
		return () => t.dispose();
	});

	let question = $state('');

	// --- the walk column ------------------------------------------------------------------
	const SPLIT_KEY = 'citadel-ask-walk';
	const narrow = new MediaQuery('(max-width: 1100px)');
	let size = $state(WALK_LIMITS.reset);
	let folded = $state(false);
	let pageEl = $state<HTMLElement>();
	let pageWidth = $state(0);
	let innerWidth = $state(0);
	let innerHeight = $state(0);

	// Read once in the browser: storage can be blocked (private window), and then the default stays.
	$effect(() => {
		try {
			const split = readSplit(localStorage.getItem(SPLIT_KEY));
			size = split.size;
			folded = split.folded;
		} catch {
			// keep the default
		}
	});
	function saveSplit() {
		try {
			localStorage.setItem(SPLIT_KEY, JSON.stringify({ size, folded }));
		} catch {
			// not remembered; the split still holds for this visit
		}
	}
	function toggleFold() {
		folded = !folded;
		saveSplit();
	}

	const wide = $derived(!narrow.current);
	const walkFolded = $derived(wide && folded);
	const walkWidth = $derived(
		walkFolded ? 'var(--walk-strip)' : `${Math.round(clampSize(size, pageWidth) * pageWidth)}px`
	);
	/** The scroller's scrollbar: columns outside it (head, composer, splitter) leave this much room. */
	const gutter = $derived(Math.max(0, pageWidth - innerWidth));
	/** Where the lanes end, in viewport px: the walk column runs from the splitter to here. */
	const right = $derived(pageEl && pageWidth ? pageEl.getBoundingClientRect().right - gutter : 0);

	// --- scrolling --------------------------------------------------------------------------
	/** Further than this from the end, in px, and "Jump to latest" shows. */
	const JUMP_SLACK = 80;
	let scroller = $state<HTMLElement>();
	let far = $state(false);
	const behavior = (): ScrollBehavior => (prefersReducedMotion.current ? 'instant' : 'smooth');

	function measure() {
		if (scroller) far = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > JUMP_SLACK;
	}
	// An answer growing under a still view moves the end without a scroll event.
	const watchGrowth: Attachment<HTMLElement> = (el) => {
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	};
	function jumpToLatest() {
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: behavior() });
	}
	/** Put the newest lane's top at the top of the view (it is at least as tall as the view). */
	async function pinLatest() {
		await tick();
		const lane = scroller?.querySelector<HTMLElement>(`[data-lane="${thread.turns.length - 1}"]`);
		if (!scroller || !lane) return;
		const top = lane.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
		scroller.scrollTo({ top, behavior: behavior() });
	}

	function ask(text: string) {
		if (field.disabled || !text.trim()) return;
		if (thread.running) {
			question = text; // asked from the top bar mid-answer: keep it ready to send
			return;
		}
		void thread.ask(text);
		question = '';
		void pinLatest();
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

<svelte:head><title>Ask · {name}</title></svelte:head>

<div
	class="ask"
	bind:this={pageEl}
	bind:clientWidth={pageWidth}
	style:--walk-width={walkWidth}
	style:--gutter="{gutter}px"
>
	<header class="head">
		<div class="title">
			<h1>Ask {name}</h1>
			{#if thread.turns.length}
				<Button size="sm" onclick={() => thread.reset()}><SquarePen aria-hidden="true" />New chat</Button>
			{/if}
		</div>
		{#if wide}
			<div class={['fold', { folded }]}>
				<Button size="sm" variant="ghost" iconOnly label={folded ? 'Show the walks' : 'Hide the walks'} onclick={toggleFold}>
					{#if folded}<PanelRightOpen aria-hidden="true" />{:else}<PanelRightClose aria-hidden="true" />{/if}
				</Button>
			</div>
		{/if}
	</header>

	<div
		class="scroller"
		bind:this={scroller}
		bind:clientWidth={innerWidth}
		bind:clientHeight={innerHeight}
		onscroll={measure}
	>
		<div class="lanes" {@attach watchGrowth}>
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
			{#each thread.turns as turn, i (i)}
				{@const selected = i === thread.selected}
				<AskLane
					{turn}
					index={i}
					brain={name}
					earlier={thread.turns.slice(0, i).flatMap((t) => t.steps)}
					{walkWidth}
					folded={walkFolded}
					root={scroller}
					minHeight={i === thread.turns.length - 1 ? innerHeight : null}
					revealed={selected ? thread.revealed : null}
					replaying={selected && thread.replaying}
					onreplay={() => thread.replay(i, prefersReducedMotion.current)}
					onrate={(rating, note) => thread.rate(i, rating, note)}
				/>
			{/each}
		</div>
	</div>

	<div class="dock">
		<div class="dock-chat">
			{#if far}
				<button type="button" class="jump" onclick={jumpToLatest}><ArrowDown aria-hidden="true" />Jump to latest</button>
			{/if}
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
		</div>
	</div>

	{#if wide && pageWidth}
		<div class="split">
			<Splitter bind:size bind:folded container={pageWidth} {right} label="Resize the walk column" onsettle={saveSplit} />
		</div>
	{/if}
</div>

<style>
	.ask {
		position: relative;
		display: flex;
		flex: 1;
		flex-direction: column;
		min-height: 0;
	}
	/* Head and dock share the lanes' columns, short of the scroller's scrollbar. */
	.head,
	.dock {
		display: grid;
		grid-template-columns: minmax(0, 1fr) var(--splitter-hit) var(--walk-width);
		padding-right: var(--gutter);
	}
	.head {
		flex: none;
		align-items: center;
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		min-width: 0;
		padding: var(--space-4) var(--space-6) var(--space-3);
	}
	.title :global(.btn) {
		margin-left: auto;
	}
	h1 {
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	.fold {
		grid-column: 3;
		justify-self: end;
		padding-right: var(--space-3);
	}
	.fold.folded {
		justify-self: center;
		padding-right: 0;
	}
	.scroller {
		flex: 1;
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		scrollbar-gutter: stable;
	}
	.intro {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 66ch;
		margin-right: calc(var(--splitter-hit) + var(--walk-width));
		padding: var(--space-6);
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
	.dock {
		flex: none;
	}
	.dock-chat {
		position: relative;
		min-width: 0;
	}
	.composer {
		display: flex;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-6) var(--space-4);
	}
	.field {
		flex: 1;
		min-width: 0;
	}
	/* Floats over the end of the chat column, just above the composer. */
	.jump {
		position: absolute;
		bottom: 100%;
		left: 50%;
		z-index: 1;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding: 0 var(--space-3);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-overlay);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		white-space: nowrap;
		cursor: pointer;
		transform: translateX(-50%);
	}
	.jump:hover {
		background: var(--color-surface);
	}
	.jump :global(svg) {
		width: var(--space-4);
		height: var(--space-4);
	}
	.split {
		position: absolute;
		top: 0;
		right: calc(var(--gutter) + var(--walk-width));
		bottom: 0;
		z-index: 2;
	}
	@media (max-width: 1100px) {
		.head,
		.dock {
			grid-template-columns: minmax(0, 1fr);
		}
		.title,
		.composer {
			padding-inline: var(--space-4);
		}
		.intro {
			margin-right: 0;
			padding-inline: var(--space-4);
		}
	}
</style>
