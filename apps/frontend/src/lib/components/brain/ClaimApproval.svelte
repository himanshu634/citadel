<!--
@component
One Keeper claim waiting for a lead, as the review page's detail pane shows it (design direction
D): its kind and subject, the statement large, why it needs a lead (one row per reason), the gap it
answers, how the Keeper got there (the `work` snippet, a `KeeperTrail`), the evidence behind it, then an optional reason and Reject or Approve under it. Use it for
claims whose status is `pending_approval`.

The approver's name is typed once in the page's header and comes in as `name`; a missing or
refused name goes back to the page through `onnameerror`, which shows it under that field. The
page does the call: `ondecide` gets the trimmed name and reason and resolves to null when it went
through, or to the error to show (`decisionError`). A 409 or 404 says so here; the page reads the
list again, so a claim someone else decided leaves it.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import NodeChip from '$lib/components/ui/NodeChip.svelte';
	import {
		CLAIM_KINDS,
		checkApproval,
		evidenceRefs,
		reasonRows,
		WHY_MAX,
		type DecisionError,
		type EvidenceRef
	} from '$lib/keeper';
	import type { Claim } from '$lib/types';
	import { nodeType } from '$lib/walk';

	type Decision = 'approve' | 'reject';
	type Props = {
		claim: Claim;
		/** The text of the gap the claim answers, when known. */
		gapText?: string | null;
		evidence: EvidenceRef[];
		/** The subject named as well as the page knows it; else from its uid. */
		subject?: EvidenceRef;
		/** The approver's name, typed in the page's header. */
		name?: string;
		ondecide: (decision: Decision, by: string, why: string) => Promise<DecisionError | null>;
		/** The name is missing or was refused: the message to show under the header's field. */
		onnameerror?: (message: string) => void;
		/** The decision being sent (the gallery sets it to show the state). */
		busy?: Decision | null;
		/** The last failure (the gallery sets it to show the state). */
		failure?: DecisionError | null;
		/** How the Keeper got to the claim (`KeeperTrail`), shown between the gap and the evidence. */
		work?: Snippet;
	};

	let {
		claim,
		gapText = null,
		evidence,
		subject,
		name = '',
		ondecide,
		onnameerror,
		busy = $bindable(null),
		failure = $bindable(null),
		work
	}: Props = $props();
	const id = $props.id();

	let why = $state('');
	let whyError = $state<string | null>(null);
	const errors = $derived({ why: whyError ?? (failure?.field === 'why' ? failure.message : undefined) });
	const banner = $derived(failure && !failure.field ? failure.message : null);
	const about = $derived(subject ?? evidenceRefs([claim.subject], () => null)[0]);
	const reasons = $derived(reasonRows(claim.critical_reasons));
	/** The gap only when it says more than the statement already does. */
	const gap = $derived(gapText && gapText.trim() !== claim.statement.trim() ? gapText : null);
	const others = $derived(evidence.filter((ref) => ref.uid !== claim.subject || evidence.length === 1));
	const LABEL_MAX = 40;
	const short = (text: string) => (text.length > LABEL_MAX ? `${text.slice(0, LABEL_MAX - 1)}…` : text);

	async function decide(decision: Decision) {
		const checked = checkApproval(name, why);
		failure = null;
		whyError = checked?.why ?? null;
		if (checked?.by) onnameerror?.(checked.by);
		if (checked) return;
		busy = decision;
		try {
			failure = await ondecide(decision, name.trim(), why.trim());
			if (failure?.field === 'by') onnameerror?.(failure.message);
		} finally {
			busy = null;
		}
	}
</script>

<article class="claim" aria-labelledby="{id}-statement">
	<div class="body">
		<p class="tags">
			<span class="kind">{CLAIM_KINDS[claim.kind] ?? claim.kind}</span>
			<span title={about.uid}><NodeChip type={nodeType(about.label)} label={short(about.title)} href={about.url ?? undefined} /></span>
		</p>
		<h2 id="{id}-statement">{claim.statement}</h2>

		<section aria-labelledby="{id}-why">
			<h3 id="{id}-why">Why it needs you</h3>
			<ul class="reasons">
				{#each reasons as reason (reason.code)}
					<li>
						<span class="mark" aria-hidden="true"></span>
						<span><span class="reason">{reason.title}</span>{#if reason.detail}<span class="detail">{reason.detail}</span>{/if}</span>
					</li>
				{/each}
			</ul>
		</section>

		{#if gap}
			<section aria-labelledby="{id}-gap">
				<h3 id="{id}-gap">The gap it answers</h3>
				<p class="gap">{gap}</p>
			</section>
		{/if}

		{@render work?.()}

		<section aria-labelledby="{id}-evidence">
			<h3 id="{id}-evidence">Evidence</h3>
			{#if others.length}
				<ul class="evidence">
					{#each others as ref (ref.uid)}
						<li title={ref.uid}>
							<NodeChip type={nodeType(ref.label)} label={short(ref.title)} href={ref.url ?? undefined} />
						</li>
					{/each}
				</ul>
			{:else}
				<p class="none">No evidence is cited.</p>
			{/if}
		</section>
	</div>

	<form
		class="decide"
		onsubmit={(e) => {
			e.preventDefault();
			void decide('approve');
		}}
	>
		{#if banner}<p class="failure" role="alert">{banner}</p>{/if}
		<div class="row">
			<div class="why">
				<Input
					label="Why (optional)"
					hideLabel
					placeholder="Why (optional, goes in the Keeper's log)"
					maxlength={WHY_MAX + 20}
					bind:value={why}
					oninput={() => (whyError = null)}
					error={errors.why}
					disabled={busy !== null}
				/>
			</div>
			<Button loading={busy === 'reject'} disabled={busy !== null} onclick={() => decide('reject')}>Reject</Button>
			<Button type="submit" variant="primary" loading={busy === 'approve'} disabled={busy !== null}>Approve</Button>
		</div>
	</form>
</article>

<style>
	.claim {
		display: flex;
		flex-direction: column;
		min-height: 0;
		height: 100%;
		background: var(--color-surface-raised);
	}
	.body {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: var(--space-6);
		min-height: 0;
		overflow: auto;
		padding: var(--space-8) var(--space-10);
	}
	.body > * {
		max-width: 48rem;
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		margin: 0;
	}
	.kind {
		padding: 0.125rem var(--space-2);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-sm);
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	h2 {
		margin: calc(-1 * var(--space-3)) 0 0;
		font-size: var(--text-2xl);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	h3 {
		margin: 0 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.reasons,
	.evidence {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.reasons li {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-top: var(--border-hair) solid var(--color-line);
	}
	.mark {
		flex: none;
		width: var(--space-2);
		height: var(--space-2);
		margin-top: 0.45em;
		border-radius: var(--radius-sm);
		background: var(--color-warning);
	}
	.reason {
		display: block;
		font-size: var(--text-md);
	}
	.detail {
		display: block;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.gap {
		margin: 0;
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		font-size: var(--text-md);
		overflow-wrap: anywhere;
	}
	.evidence {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.evidence li {
		max-width: 100%;
	}
	.none {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.decide {
		display: flex;
		flex: none;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-10);
		border-top: var(--border-hair) solid var(--color-line);
		background: var(--color-surface);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		align-items: flex-start;
	}
	.why {
		flex: 1 1 16rem;
		min-width: 0;
	}
	.failure {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	@media (max-width: 40rem) {
		.body,
		.decide {
			padding-inline: var(--space-4);
		}
	}
</style>
