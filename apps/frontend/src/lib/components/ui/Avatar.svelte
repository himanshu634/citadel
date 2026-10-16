<!--
@component
Initials on the node colour of what it stands for (person, team, system). Decorative: always
place the name next to it.
-->
<script lang="ts">
	import type { NodeType } from '$lib/types';

	type Props = { name: string; type?: NodeType; size?: 'sm' | 'md' | 'lg' };

	let { name, type = 'person', size = 'md' }: Props = $props();

	const initials = $derived(
		name
			.split(/[\s_-]+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => w[0]?.toUpperCase())
			.join('')
	);
</script>

<span class={['avatar', size]} style:--node="var(--node-{type})" aria-hidden="true">{initials}</span>

<style>
	.avatar {
		--s: 2rem;
		display: inline-grid;
		place-items: center;
		width: var(--s);
		height: var(--s);
		flex: none;
		border-radius: var(--radius-full);
		background: color-mix(in oklab, var(--node) 18%, var(--color-surface));
		color: var(--node);
		font-size: calc(var(--s) * 0.38);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		letter-spacing: 0.02em;
	}
	.sm {
		--s: 1.5rem;
	}
	.lg {
		--s: 2.5rem;
	}
</style>
