<!--
@component
The Keeper's log in the Systems page's rail (design direction A2), newest first: the time, who did
what in words ("pm opened a follow-up", "Keeper wrote a claim"; an auto-accept reads as the
Keeper), then why. A line about a gap says which one; a line about a claim the rail shows (a
pending one) links to its card.
-->
<script lang="ts">
	import { logSentence, logTime, logWhy } from '$lib/keeper';
	import type { LogEntry } from '$lib/types';

	type Props = {
		entries: LogEntry[];
		/** A gap's text by uid, for the lines about one. */
		gapText?: (uid: string) => string | null;
		/** Where the page shows a claim (its card), or null when it does not. */
		claimHref?: (uid: string) => string | null;
		/** For tests and the gallery: the clock the times read. */
		now?: number;
	};

	let { entries, gapText = () => null, claimHref = () => null, now }: Props = $props();
</script>

{#if entries.length === 0}
	<p class="none">Nothing yet. Each gap the Keeper opens, claim it writes and decision a lead makes is logged here.</p>
{:else}
	<ol class="log">
		{#each entries as entry (entry.uid)}
			{@const why = logWhy(entry)}
			{@const gap = entry.gap ? gapText(entry.gap) : null}
			{@const href = entry.claim ? claimHref(entry.claim) : null}
			<li>
				<time class="at tabular" datetime={entry.at}>{logTime(entry.at, now)}</time>
				<div class="body">
					<span class="what">{logSentence(entry)}{#if why}<span class="muted">: {why}</span>{/if}</span>
					{#if gap || href}
						<span class="ref">
							{#if gap}<span>Gap: {gap}</span>{/if}
							{#if href}<a {href}>See the claim</a>{/if}
						</span>
					{/if}
				</div>
			</li>
		{/each}
	</ol>
{/if}

<style>
	.none {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.log {
		display: flex;
		flex-direction: column;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-top: var(--border-hair) solid var(--color-line);
		font-size: var(--text-sm);
	}
	.at {
		flex: none;
		min-width: var(--space-10);
		padding-top: 0.0625rem;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.what {
		overflow-wrap: anywhere;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.ref {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
	.ref a {
		color: var(--color-accent);
		font-weight: var(--weight-semibold);
	}
</style>
