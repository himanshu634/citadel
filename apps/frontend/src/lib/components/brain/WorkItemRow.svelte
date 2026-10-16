<!--
@component
One work item (PR, issue or thread) in a list: kind icon, title, who and when, state badge.
-->
<script lang="ts">
	import { CircleDot, GitPullRequest, MessagesSquare } from '@lucide/svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import type { WorkItem } from '$lib/types';

	type Props = { item: WorkItem };

	let { item }: Props = $props();

	const KINDS = {
		pull_request: { icon: GitPullRequest, label: 'PR' },
		issue: { icon: CircleDot, label: 'Issue' },
		ticket: { icon: CircleDot, label: 'Ticket' },
		thread: { icon: MessagesSquare, label: 'Thread' }
	} as const;
	const kind = $derived(KINDS[item.kind] ?? KINDS.thread);
	const Icon = $derived(kind.icon);
	const tone = $derived(
		item.state === 'open' ? 'success' : item.state === 'merged' ? 'accent' : 'neutral'
	);
	const date = $derived(
		item.date && !Number.isNaN(new Date(item.date).getTime())
			? new Date(item.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
			: null
	);
	// Author, date and system are each optional: join only the ones the source gave.
	const meta = $derived(
		[`${kind.label}${item.number ? ` #${item.number}` : ''}`, item.author, date, item.system]
			.filter(Boolean)
			.join(', ')
	);
</script>

<div class="row">
	<span class="icon" aria-hidden="true"><Icon /></span>
	<div class="main">
		<span class="title">{item.title}</span>
		<span class="meta">{meta}</span>
	</div>
	<Badge {tone}>{item.state}</Badge>
</div>

<style>
	.row {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding-block: var(--space-3);
		min-width: 0;
	}
	.icon {
		color: var(--node-work-item);
		padding-top: 2px;
	}
	.icon :global(svg) {
		width: 1rem;
		height: 1rem;
	}
	.main {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
	}
	.title {
		font-weight: var(--weight-medium);
		overflow-wrap: anywhere;
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
</style>
