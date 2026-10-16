<!--
@component
The past chats of one company, newest first: each row is a link to the chat (its first question,
how many questions it holds and when it last moved). The open chat is marked; a chat still
answering says so with a spinner, a failed or stopped one says it in words. Delete asks once
inline before it goes. Shared by everyone who opens the company: there are no users yet.
-->
<script lang="ts">
	import { CircleAlert, LoaderCircle, MessagesSquare, Trash2 } from '@lucide/svelte';
	import Button from '../ui/Button.svelte';
	import type { ThreadSummary } from '$lib/types';
	import { ago } from '$lib/time';

	type Props = {
		threads: ThreadSummary[];
		/** The open chat's id. */
		current?: string | null;
		/** The link for a chat. */
		hrefOf: (id: string) => string;
		loading?: boolean;
		error?: string | null;
		/** More chats to read. */
		more?: boolean;
		/** The chat being deleted. */
		deleting?: string | null;
		onmore?: () => void;
		ondelete?: (id: string) => void;
		/** For tests and the gallery: the clock relative times read. */
		now?: number;
	};

	let {
		threads,
		current = null,
		hrefOf,
		loading = false,
		error = null,
		more = false,
		deleting = null,
		onmore,
		ondelete,
		now = Date.now()
	}: Props = $props();

	let confirming = $state<string | null>(null);

	function meta(t: ThreadSummary): string {
		const questions = t.turns === 1 ? '1 question' : `${t.turns} questions`;
		return `${questions} · ${ago(t.updated_at, now)}`;
	}
</script>

<nav class="chats" aria-label="Past chats">
	<h2 class="title">Chats</h2>
	{#if error}
		<p class="error" role="alert"><CircleAlert aria-hidden="true" />{error}</p>
	{/if}
	{#if threads.length === 0 && !loading}
		<p class="empty"><MessagesSquare aria-hidden="true" />No chats yet. Questions you ask are kept here.</p>
	{/if}
	<ul>
		{#each threads as t (t.id)}
			{@const open = t.id === current}
			<li class={['chat', { open }]}>
				<a class="link" href={hrefOf(t.id)} aria-current={open ? 'page' : undefined}>
					<span class="name">{t.title}</span>
					<span class="meta">
						{#if t.last_status === 'running'}
							<LoaderCircle class="spin" aria-hidden="true" />answering ·
						{:else if t.last_status === 'failed'}
							<span class="bad">failed</span> ·
						{:else if t.last_status === 'stopped'}
							stopped ·
						{/if}
						{meta(t)}
					</span>
				</a>
				{#if confirming === t.id}
					<div class="confirm" role="group" aria-label="Delete {t.title}?">
						<Button
							size="sm"
							variant="danger"
							loading={deleting === t.id}
							onclick={() => {
								ondelete?.(t.id);
								confirming = null;
							}}>Delete</Button
						>
						<Button size="sm" variant="ghost" onclick={() => (confirming = null)}>Keep</Button>
					</div>
				{:else}
					<span class="tools">
						<Button
							size="sm"
							variant="ghost"
							iconOnly
							label="Delete chat {t.title}"
							disabled={t.last_status === 'running' || deleting === t.id}
							onclick={() => (confirming = t.id)}><Trash2 aria-hidden="true" /></Button
						>
					</span>
				{/if}
			</li>
		{/each}
	</ul>
	{#if loading}
		<p class="meta loading" role="status"><LoaderCircle class="spin" aria-hidden="true" />Loading chats</p>
	{:else if more}
		<div class="more"><Button size="sm" variant="ghost" onclick={() => onmore?.()}>Older chats</Button></div>
	{/if}
</nav>

<style>
	.chats {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}
	.title {
		padding-inline: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	ul {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.chat {
		position: relative;
		display: flex;
		align-items: center;
		border-radius: var(--radius-md);
	}
	.chat:hover,
	.chat:focus-within {
		background: var(--color-surface);
	}
	.chat.open {
		background: var(--color-surface);
		outline: var(--border-hair) solid var(--color-line);
	}
	.link {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		padding: var(--space-2);
		border-radius: var(--radius-md);
		color: var(--color-text);
		text-decoration: none;
	}
	.link:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: -2px;
	}
	.name {
		overflow: hidden;
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meta {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.meta :global(svg),
	.error :global(svg),
	.empty :global(svg) {
		flex: none;
		width: 0.875rem;
		height: 0.875rem;
	}
	.bad {
		color: var(--color-danger);
		font-weight: var(--weight-semibold);
	}
	.tools {
		opacity: 0;
		padding-right: var(--space-1);
	}
	.chat:hover .tools,
	.chat:focus-within .tools {
		opacity: 1;
	}
	@media (hover: none) {
		.tools {
			opacity: 1;
		}
	}
	.confirm {
		display: flex;
		gap: var(--space-1);
		padding-right: var(--space-1);
	}
	.error,
	.empty {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		padding-inline: var(--space-2);
		font-size: var(--text-sm);
	}
	.error {
		color: var(--color-danger);
	}
	.empty {
		color: var(--color-text-muted);
	}
	.loading {
		padding-inline: var(--space-2);
	}
	.more {
		display: flex;
	}
</style>
