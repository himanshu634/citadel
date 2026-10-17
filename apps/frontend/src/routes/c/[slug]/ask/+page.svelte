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
again. Every chat is kept on the server: the past chats column (`ChatList`, foldable, kept in
`citadel-ask-history`) lists them, `?thread=<id>` opens one (a reload or a shared link reopens
it), and each lane shows how it answered (`TurnTimeline`, folded under the answer). A chip under
the question field picks the Claude model for the next question (`ModelPicker`, direction P;
Haiku 5.5 by default, kept in this browser); each answer says which model wrote it, and a
follow-up on another model says so.
-->
<script lang="ts">
	import {
		ArrowDown,
		History,
		LoaderCircle,
		PanelLeftClose,
		PanelRightClose,
		PanelRightOpen,
		SquarePen
	} from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { tick, untrack } from 'svelte';
	import type { Attachment } from 'svelte/attachments';
	import { prefersReducedMotion } from 'svelte/motion';
	import { MediaQuery } from 'svelte/reactivity';
	import { Banner, Button, ChatList, Input, ModelPicker } from '$lib';
	import { AskThread } from '$lib/ask.svelte';
	import { Chats } from '$lib/chats.svelte';
	import { ModelChoice } from '$lib/models.svelte';
	import AskLane from '$lib/components/brain/AskLane.svelte';
	import Splitter from '$lib/components/ui/Splitter.svelte';
	import { getCompanies } from '$lib/companies.svelte';
	import { WALK_LIMITS, clampSize, readSplit } from '$lib/splitter';
	import { askFieldOf } from '$lib/topbar';
	import { api } from '$lib/api/client';
	import { githubRepos } from '$lib/links';

	let { data } = $props();
	const companies = getCompanies();
	const company = $derived(companies.byslug(data.slug));
	const field = $derived(askFieldOf(company));
	const name = $derived(company?.name ?? data.slug);

	// One conversation and one chat list per company: switching company on the rail starts fresh.
	const slug = $derived(data.slug);
	const chats = $derived(new Chats(slug));
	const thread = $derived(
		new AskThread(
			slug,
			(id) => {
				if (page.url.searchParams.get('thread') !== id) void openUrl(id);
				void chats.refresh();
			},
			() => void chats.refresh()
		)
	);
	$effect(() => {
		const t = thread;
		return () => t.dispose();
	});
	$effect(() => {
		void chats.refresh();
	});

	// The company's GitHub repos, so a bare `#12` in an answer opens there. Best effort: without
	// them, refs link only to what the answer's walk saw.
	let repos = $state<string[]>([]);
	$effect(() => {
		const s = slug;
		repos = [];
		api.sources(s).then(
			(out) => {
				if (s === slug) repos = githubRepos(out.sources);
			},
			() => {}
		);
	});

	// The same list for every company; the pick is kept in this browser.
	const models = new ModelChoice();
	$effect(() => {
		void models.load();
	});

	/** The model that wrote a turn: the answer's (it may differ after a fallback), else the one asked for. */
	function modelOf(t: (typeof thread.turns)[number]): string | null {
		return t.answer?.model ?? t.calls.at(-1)?.model ?? t.model;
	}

	const wanted = $derived(page.url.searchParams.get('thread'));
	// The address names the open chat: reopen it when it changes (a link, back, a reload); a bare
	// address (the Ask link, New chat) means a new chat. A running answer is never cut off: a chat
	// picked meanwhile opens when it ends (the effect reads `running` for that).
	$effect(() => {
		const id = wanted;
		if (thread.running) return;
		untrack(() => {
			if (id && id !== thread.threadId) void thread.load(id).then(pinLatest);
			else if (!id && thread.threadId) thread.reset();
		});
	});

	function hrefOf(id: string): string {
		return `${page.url.pathname}?thread=${encodeURIComponent(id)}`;
	}

	function openUrl(id: string | null) {
		const url = new URL(page.url);
		if (id) url.searchParams.set('thread', id);
		else url.searchParams.delete('thread');
		return goto(url, { replaceState: !!id && !wanted, noScroll: true, keepFocus: true });
	}

	function newChat() {
		thread.reset();
		void openUrl(null);
	}

	async function remove(id: string) {
		if (await chats.remove(id)) {
			if (id === thread.threadId) newChat();
		}
	}

	// --- the past chats column ----------------------------------------------------------------
	const HISTORY_KEY = 'citadel-ask-history';
	let historyOpen = $state(true);
	// Read once in the browser, like the split: blocked storage keeps it open.
	$effect(() => {
		try {
			historyOpen = localStorage.getItem(HISTORY_KEY) !== 'folded';
		} catch {
			// keep it open
		}
	});
	function toggleHistory() {
		historyOpen = !historyOpen;
		try {
			localStorage.setItem(HISTORY_KEY, historyOpen ? 'open' : 'folded');
		} catch {
			// not remembered; it still folds for this visit
		}
	}

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
		void thread.ask(text, models.selected);
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

<div class={['ask-page', { 'history-open': historyOpen }]}>
	{#if historyOpen}
		<aside class="history" aria-label="Past chats">
			<div class="history-head">
				<Button size="sm" onclick={newChat} disabled={!thread.turns.length && !thread.threadId}
					><SquarePen aria-hidden="true" />New chat</Button
				>
				<Button size="sm" variant="ghost" iconOnly label="Hide past chats" onclick={toggleHistory}>
					<PanelLeftClose aria-hidden="true" />
				</Button>
			</div>
			<ChatList
				threads={chats.threads}
				current={thread.threadId}
				{hrefOf}
				loading={chats.loading}
				error={chats.error}
				more={chats.next !== null}
				deleting={chats.deleting}
				onmore={() => chats.more()}
				ondelete={remove}
			/>
		</aside>
	{/if}
<div
	class="ask"
	bind:this={pageEl}
	bind:clientWidth={pageWidth}
	style:--walk-width={walkWidth}
	style:--gutter="{gutter}px"
>
	<header class="head">
		<div class="title">
			{#if !historyOpen}
				<Button size="sm" variant="ghost" iconOnly label="Show past chats" onclick={toggleHistory}>
					<History aria-hidden="true" />
				</Button>
			{/if}
			<h1>Ask {name}</h1>
			{#if !historyOpen && (thread.turns.length || thread.threadId)}
				<Button size="sm" class="new" onclick={newChat}><SquarePen aria-hidden="true" />New chat</Button>
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
			{#if thread.loadError}
				<div class="notice"><Banner tone="danger" title="This chat could not be opened">{thread.loadError}</Banner></div>
			{/if}
			{#if thread.loading}
				<p class="opening" role="status"><LoaderCircle class="spin" aria-hidden="true" />Opening the chat</p>
			{:else if thread.turns.length === 0}
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
				{@const was = i > 0 ? modelOf(thread.turns[i - 1]) : null}
				{@const wrote = modelOf(turn)}
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
					answeredBy={turn.answer?.model ? (models.nameOf(turn.answer.model) ?? turn.answer.model) : null}
					switched={was && wrote && was !== wrote ? { from: models.nameOf(was) ?? was, to: models.nameOf(wrote) ?? wrote } : null}
					{repos}
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
				<Input
					label="Your question"
					hideLabel
					placeholder={field.disabled ? field.placeholder : thread.turns.length ? 'Ask a follow-up' : field.placeholder}
					disabled={field.disabled}
					bind:value={question}
				/>
				<div class="controls">
					{#if models.models.length}
						<ModelPicker
							models={models.models}
							selected={models.selected}
							defaultId={models.defaultId}
							disabled={thread.running}
							onpick={(id) => models.pick(id)}
						/>
					{/if}
					{#if thread.running}
						<Button onclick={() => thread.stop()}>Stop</Button>
					{:else}
						<Button type="submit" variant="primary" disabled={field.disabled || !question.trim()}>Ask</Button>
					{/if}
				</div>
			</form>
		</div>
	</div>

	{#if wide && pageWidth}
		<div class="split">
			<Splitter bind:size bind:folded container={pageWidth} {right} label="Resize the walk column" onsettle={saveSplit} />
		</div>
	{/if}
</div>
</div>

<style>
	.ask-page {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.history {
		display: flex;
		flex: none;
		flex-direction: column;
		gap: var(--space-3);
		width: var(--sidebar-width);
		min-height: 0;
		padding: var(--space-4) var(--space-3);
		overflow-y: auto;
		border-right: var(--border-hair) solid var(--color-line);
	}
	.history-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.notice {
		max-width: 66ch;
		padding: var(--space-4) var(--space-6) 0;
	}
	.opening {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-6);
		color: var(--color-text-muted);
	}
	.opening :global(svg) {
		width: var(--space-4);
		height: var(--space-4);
	}
	.ask {
		min-width: 0;
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
	.title :global(.new) {
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
	/* Positioned, so hidden live text deep in a lane is placed (and clipped) in here, not on the page. */
	.scroller {
		position: relative;
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
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-6) var(--space-4);
	}
	.controls {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.controls :global(.btn) {
		margin-left: auto;
	}
	/* Floats over the end of the chat column, just above the composer, on its content edge. */
	.jump {
		position: absolute;
		bottom: 100%;
		left: var(--space-6);
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
	/* Below 1400px the past chats sit above the lanes, as a short scrolling strip. */
	@media (max-width: 1400px) {
		.ask-page.history-open {
			flex-direction: column;
		}
		.history {
			width: auto;
			max-height: 12rem;
			border-right: 0;
			border-bottom: var(--border-hair) solid var(--color-line);
		}
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
		.jump {
			left: var(--space-4);
		}
	}
</style>
