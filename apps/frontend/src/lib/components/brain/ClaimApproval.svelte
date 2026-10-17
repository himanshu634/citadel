<!--
@component
One Keeper claim waiting for a lead, as the Systems page's rail lists it (design direction A2):
its status and kind, the statement, why it needs a lead (in words), the gap it answers, the
evidence behind it, then a typed name (there is no sign-in), an optional reason, and Approve or
Reject. Use it for claims whose status is `pending_approval`.

The page does the call: `ondecide` gets the trimmed name and reason and resolves to null when it
went through, or to the error to show (`decisionError`). A 409 or 404 says so here; the page
reads the list again, so a claim someone else decided leaves it.
-->
<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import NodeChip from '$lib/components/ui/NodeChip.svelte';
	import { CLAIM_KINDS, checkApproval, criticalLine, NAME_MAX, WHY_MAX, type ApprovalErrors, type DecisionError, type EvidenceRef } from '$lib/keeper';
	import type { Claim } from '$lib/types';
	import { nodeType } from '$lib/walk';

	type Decision = 'approve' | 'reject';
	type Props = {
		claim: Claim;
		/** The text of the gap the claim answers, when known. */
		gapText?: string | null;
		evidence: EvidenceRef[];
		/** The approver's name; shared by every card, so it is typed once. */
		name?: string;
		ondecide: (decision: Decision, by: string, why: string) => Promise<DecisionError | null>;
		/** The decision being sent (the gallery sets it to show the state). */
		busy?: Decision | null;
		/** The last failure (the gallery sets it to show the state). */
		failure?: DecisionError | null;
	};

	let {
		claim,
		gapText = null,
		evidence,
		name = $bindable(''),
		ondecide,
		busy = $bindable(null),
		failure = $bindable(null)
	}: Props = $props();
	const id = $props.id();

	let why = $state('');
	let checked = $state<ApprovalErrors | null>(null);
	const errors = $derived({
		by: checked?.by ?? (failure?.field === 'by' ? failure.message : undefined),
		why: checked?.why ?? (failure?.field === 'why' ? failure.message : undefined)
	});
	const banner = $derived(failure && !failure.field ? failure.message : null);
	const LABEL_MAX = 32;
	const short = (text: string) => (text.length > LABEL_MAX ? `${text.slice(0, LABEL_MAX - 1)}…` : text);

	async function decide(decision: Decision) {
		checked = checkApproval(name, why);
		failure = null;
		if (checked) return;
		busy = decision;
		try {
			failure = await ondecide(decision, name.trim(), why.trim());
		} finally {
			busy = null;
		}
	}
</script>

<article class="claim" aria-labelledby="{id}-statement">
	<p class="tags">
		<Badge tone="warning">pending_approval</Badge>
		<span class="kind">{CLAIM_KINDS[claim.kind] ?? claim.kind}</span>
	</p>
	<h3 id="{id}-statement">{claim.statement}</h3>
	<p class="why">
		{criticalLine(claim.critical_reasons)}
		{#if gapText}From the gap: {gapText}{/if}
	</p>

	{#if evidence.length}
		<ul class="evidence" aria-label="Evidence">
			{#each evidence as ref (ref.uid)}
				<li title={ref.uid}>
					<NodeChip type={nodeType(ref.label)} label={short(ref.title)} href={ref.url ?? undefined} />
				</li>
			{/each}
		</ul>
	{:else}
		<p class="why">No evidence is cited.</p>
	{/if}

	<form
		class="decide"
		onsubmit={(e) => {
			e.preventDefault();
			void decide('approve');
		}}
	>
		<Input
			label="Your name"
			placeholder="Who decides this"
			autocomplete="name"
			maxlength={NAME_MAX + 20}
			bind:value={name}
			oninput={() => (checked = null)}
			error={errors.by}
			disabled={busy !== null}
		/>
		<Input
			label="Why (optional)"
			placeholder="Goes in the Keeper's log"
			maxlength={WHY_MAX + 20}
			bind:value={why}
			oninput={() => (checked = null)}
			error={errors.why}
			disabled={busy !== null}
		/>
		{#if banner}<p class="failure" role="alert">{banner}</p>{/if}
		<div class="actions">
			<Button type="submit" size="sm" loading={busy === 'approve'} disabled={busy !== null}>Approve</Button>
			<Button size="sm" variant="ghost" loading={busy === 'reject'} disabled={busy !== null} onclick={() => decide('reject')}
				>Reject</Button
			>
		</div>
	</form>
</article>

<style>
	.claim {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
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
	h3 {
		margin: 0;
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	.why {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		overflow-wrap: anywhere;
	}
	.evidence {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.evidence li {
		max-width: 100%;
	}
	.decide {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.failure {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
