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

	const Icon = $derived(
		item.kind === 'pull_request' ? GitPullRequest : item.kind === 'issue' ? CircleDot : MessagesSquare
	);
	const kindLabel = $derived(
		item.kind === 'pull_request' ? 'PR' : item.kind === 'issue' ? 'Issue' : 'Thread'
	);
	const tone = $derived(
		item.state === 'open' ? 'success' : item.state === 'merged' ? 'accent' : 'neutral'
	);
	const date = $derived(
		new Date(item.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
	);
</script>

<div class="row">
	<span class="icon" aria-hidden="true"><Icon /></span>
	<div class="main">
		<span class="title">{item.title}</span>
		<span class="meta">
			{kindLabel}{item.number ? ` #${item.number}` : ''}, {item.author}, {date}{item.system
				? `, ${item.system}`
				: ''}
		</span>
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
