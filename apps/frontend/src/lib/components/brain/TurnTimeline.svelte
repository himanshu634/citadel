<!--
@component
How one answer came about, response by response: what Claude said, its reasoning when the API
returned it (folded), and every tool it called, each with where it ran: a graph tool, the answer
check, a tool on an MCP server (named) or an Anthropic server tool. Graph calls show their rows
count or error from the walk; MCP and server calls show their result, folded. The whole timeline
folds under one summary line; it starts open while the answer runs.
-->
<script lang="ts">
	import { Check, ChevronRight, CircleAlert, LoaderCircle } from '@lucide/svelte';
	import Badge from '../ui/Badge.svelte';
	import type { AskCall, AskLlmEvent, CallKind, WalkStep } from '$lib/types';
	import { stepCall } from '$lib/walk';

	type Props = {
		calls: AskLlmEvent[];
		/** The turn's walk, for the status of graph calls and answer checks. */
		steps?: WalkStep[];
		running?: boolean;
	};

	let { calls, steps = [], running = false }: Props = $props();

	// Starts open while the answer runs; the reader's own toggle wins from then on.
	let open = $state(false);
	let touched = $state(false);
	const shown = $derived(touched ? open : running);

	const byId = $derived(new Map(steps.map((s) => [s.id, s])));
	const toolCount = $derived(calls.reduce((n, c) => n + c.calls.length, 0));
	const tokens = $derived(
		calls.reduce((n, c) => n + c.usage.input + c.usage.output + c.usage.cache_read + c.usage.cache_write, 0)
	);
	const summary = $derived(
		[
			calls.length === 1 ? '1 response' : `${calls.length} responses`,
			toolCount === 1 ? '1 tool call' : `${toolCount} tool calls`,
			tokens ? `${tokens.toLocaleString()} tokens` : null
		]
			.filter(Boolean)
			.join(' · ')
	);

	const KIND: Record<CallKind, string> = {
		graph: 'Graph tool',
		submit: 'Answer check',
		mcp: 'MCP',
		server: 'Server tool',
		archive: 'Archivist tool'
	};

	type State = { icon: 'run' | 'ok' | 'bad'; text: string };
	function stateOf(call: AskCall): State {
		if (call.kind === 'mcp' || call.kind === 'server') {
			return call.error ? { icon: 'bad', text: 'failed' } : { icon: 'ok', text: 'done' };
		}
		const step = byId.get(call.id);
		if (!step || step.status === 'running') return { icon: 'run', text: 'running' };
		if (step.error?.startsWith('Not run')) return { icon: 'bad', text: 'not run' };
		if (step.error) return { icon: 'bad', text: call.kind === 'submit' ? 'sent back' : 'failed' };
		if (call.kind === 'submit') return { icon: 'ok', text: 'accepted' };
		return { icon: 'ok', text: step.count === 1 ? '1 row' : `${step.count ?? 0} rows` };
	}
	const what = (call: AskCall) => (call.kind === 'submit' ? 'submit_answer' : stepCall(call));
</script>

{#if calls.length}
	<details
		class="timeline"
		open={shown}
		ontoggle={(e) => {
			const now = (e.currentTarget as HTMLDetailsElement).open;
			if (now !== shown) {
				touched = true;
				open = now;
			}
		}}
	>
		<summary>
			<ChevronRight class="chev" aria-hidden="true" />
			<span class="label">How it answered</span>
			<span class="meta">{summary}</span>
		</summary>
		<ol class="responses">
			{#each calls as call (call.seq)}
				<li class="response">
					<p class="who">
						<span class="label">Claude</span>
						<span class="meta tabular">
							{[call.model, call.ms != null ? `${call.ms} ms` : null, call.stop].filter(Boolean).join(' · ')}
						</span>
					</p>
					{#if call.thinking}
						<details class="fold">
							<summary><ChevronRight class="chev" aria-hidden="true" />Reasoning</summary>
							<p class="body muted">{call.thinking}</p>
						</details>
					{/if}
					{#if call.text}
						<p class="body">{call.text}</p>
					{/if}
					{#if call.calls.length}
						<ul class="calls">
							{#each call.calls as tool (tool.id)}
								{@const s = stateOf(tool)}
								<li class={['call', s.icon]}>
									<span class="mark" aria-hidden="true">
										{#if s.icon === 'run'}<LoaderCircle class="spin" />{:else if s.icon === 'bad'}<CircleAlert />{:else}<Check />{/if}
									</span>
									<Badge tone={tool.kind === 'mcp' ? 'accent' : 'neutral'}
										>{KIND[tool.kind]}{tool.server ? ` · ${tool.server}` : ''}</Badge
									>
									<code class="what">{what(tool)}</code>
									<span class="meta">{s.text}</span>
									{#if tool.result || tool.error}
										<details class="fold result">
											<summary><ChevronRight class="chev" aria-hidden="true" />Result</summary>
											<pre>{tool.error ?? tool.result}</pre>
										</details>
									{/if}
								</li>
							{/each}
						</ul>
					{:else if !call.text && !call.thinking}
						<p class="meta">No text and no tool calls.</p>
					{/if}
				</li>
			{/each}
		</ol>
	</details>
{/if}

<style>
	.timeline {
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		list-style: none;
		cursor: pointer;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	.timeline > summary {
		flex-wrap: wrap;
		min-height: var(--control-sm);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-md);
	}
	summary:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: -2px;
	}
	summary :global(.chev) {
		flex: none;
		width: 0.875rem;
		height: 0.875rem;
		color: var(--color-text-muted);
		transition: transform var(--duration-fast) var(--ease-out);
	}
	details[open] > summary :global(.chev) {
		transform: rotate(90deg);
	}
	.label {
		white-space: nowrap;
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.responses {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-1) var(--space-3) var(--space-3);
		list-style: none;
	}
	.response {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-left: var(--space-3);
		border-left: var(--border-hair) solid var(--color-line-strong);
	}
	.who {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
	}
	.body {
		font-size: var(--text-md);
		line-height: var(--leading-body);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.fold > summary {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
	}
	.fold > .body {
		margin-top: var(--space-1);
	}
	.calls {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.call {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}
	.mark {
		display: inline-flex;
		color: var(--color-text-muted);
	}
	.mark :global(svg) {
		width: 0.875rem;
		height: 0.875rem;
	}
	.call.ok .mark {
		color: var(--color-success);
	}
	.call.bad .mark {
		color: var(--color-danger);
	}
	.what {
		overflow: hidden;
		flex: 1 1 12rem;
		min-width: 0;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.result {
		flex-basis: 100%;
	}
	pre {
		overflow: auto;
		max-height: 16rem;
		margin-top: var(--space-1);
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
</style>
