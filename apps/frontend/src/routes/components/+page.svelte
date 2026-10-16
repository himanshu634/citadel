<!-- Living gallery of the design system: every component and its states. Keep it in sync. -->
<script lang="ts">
	import { Inbox, Plus, Search, Trash2 } from '@lucide/svelte';
	import {
		ActivityBars,
		Avatar,
		Badge,
		Button,
		Card,
		CitedAnswer,
		Dialog,
		EmptyState,
		EntityRow,
		GraphPath,
		Input,
		Menu,
		NodeChip,
		Stat,
		Tabs,
		Tooltip,
		WorkItemRow
	} from '$lib';
	import { featuredAnswer, recentWork } from '$lib/data/sample';
	import { NODE_LABELS, type NodeType } from '$lib/types';

	const nodeTypes = Object.keys(NODE_LABELS) as NodeType[];
	let dialogOpen = $state(false);
	let sort = $state('recent');
	let name = $state('');
	let tab = $state('answer');

	const swatches = [
		['--color-ground', 'Ground'],
		['--color-surface', 'Surface'],
		['--color-surface-raised', 'Raised'],
		['--color-surface-sunken', 'Sunken'],
		['--color-text', 'Text'],
		['--color-text-muted', 'Muted text'],
		['--color-line-strong', 'Strong line'],
		['--color-accent', 'Accent'],
		['--color-accent-soft', 'Accent soft'],
		['--color-success', 'Success'],
		['--color-warning', 'Warning'],
		['--color-danger', 'Danger']
	];
	const typeScale = [
		['--text-3xl', '32', 'Stat values'],
		['--text-2xl', '24', 'Page titles'],
		['--text-xl', '20', 'Dialog titles'],
		['--text-lg', '16', 'Answers and body copy'],
		['--text-md', '14', 'Interface default'],
		['--text-sm', '13', 'Secondary rows'],
		['--text-xs', '12', 'Meta and chips']
	];
</script>

<svelte:head><title>Components | Citadel</title></svelte:head>

<div class="page">
	<header>
		<h1>Components</h1>
		<p>
			Direction H, wide type and a calm body. Rules are in <code>apps/frontend/design-system.md</code>.
			Switch the theme from the top bar to check both modes.
		</p>
	</header>

	<Card title="Colour">
		<div class="swatches">
			{#each swatches as [token, label] (token)}
				<div class="swatch">
					<span style:background="var({token})"></span>
					<b>{label}</b><code>{token}</code>
				</div>
			{/each}
		</div>
		<h3 class="sub">Graph node types</h3>
		<div class="row">
			{#each nodeTypes as t (t)}<NodeChip type={t} label={NODE_LABELS[t]} />{/each}
		</div>
	</Card>

	<Card title="Type">
		<ul class="scale">
			{#each typeScale as [token, px, use] (token)}
				<li>
					<span style:font-size="var({token})">The session table was the main source of load</span>
					<small>{px}px, {use}</small>
				</li>
			{/each}
		</ul>
		<h3 class="sub">Width carries hierarchy</h3>
		<div class="widths">
			<span style:font-variation-settings="'wdth' 125" class="w">Brand 125</span>
			<span style:font-variation-settings="'wdth' 118" class="w">Heading 118</span>
			<span style:font-variation-settings="'wdth' 112" class="w">Label 112</span>
			<span style:font-variation-settings="'wdth' 100" class="w">Body 100</span>
		</div>
	</Card>

	<div class="two">
		<Card title="Button">
			<div class="stack">
				<div class="row">
					<Button variant="primary"><Plus aria-hidden="true" />Add company</Button>
					<Button>Secondary</Button>
					<Button variant="ghost">Ghost</Button>
					<Button variant="danger"><Trash2 aria-hidden="true" />Delete graph</Button>
				</div>
				<div class="row">
					<Button size="sm">Small</Button>
					<Button>Medium</Button>
					<Button size="lg">Large</Button>
					<Button iconOnly label="Search"><Search aria-hidden="true" /></Button>
					<Button disabled>Disabled</Button>
					<Button loading>Syncing</Button>
				</div>
			</div>
		</Card>

		<Card title="Badge and avatar">
			<div class="stack">
				<div class="row">
					<Badge>closed</Badge>
					<Badge tone="accent">merged</Badge>
					<Badge tone="success">open</Badge>
					<Badge tone="warning">stale</Badge>
					<Badge tone="danger">sync failed</Badge>
				</div>
				<div class="row">
					<Avatar name="Alice Kim" size="sm" />
					<Avatar name="Alice Kim" />
					<Avatar name="Alice Kim" size="lg" />
					<Avatar name="identity" type="team" />
					<Avatar name="Web app" type="system" />
				</div>
			</div>
		</Card>
	</div>

	<div class="two">
		<Card title="Input">
			<div class="stack">
				<Input label="Company name" placeholder="Acme Inc" hint="Shown in the top bar" bind:value={name} />
				<Input label="Slug" value="acme inc" error="Use lowercase letters, digits and dashes only" />
				<Input label="Search" hideLabel type="search" placeholder="Search people and systems">
					{#snippet leading()}<Search />{/snippet}
				</Input>
			</div>
		</Card>

		<Card title="Menu, tooltip, dialog">
			<div class="row">
				<Menu
					heading="Sort by"
					items={[
						{ value: 'recent', label: 'Most recent', selected: sort === 'recent' },
						{ value: 'active', label: 'Most active', selected: sort === 'active' },
						{ value: 'name', label: 'Name', selected: sort === 'name' }
					]}
					onselect={(v) => (sort = v)}
				>
					{#snippet trigger(props)}<Button {...props}>Sort: {sort}</Button>{/snippet}
				</Menu>
				<Tooltip text="Graphs are named brain_<slug>">
					{#snippet trigger(props)}<Button {...props} variant="ghost">Hover me</Button>{/snippet}
				</Tooltip>
				<Dialog
					bind:open={dialogOpen}
					title="Delete brain_synthetic?"
					description="This removes every node and relationship in the graph. Raw caches in data/ are kept, so you can ingest again."
				>
					{#snippet trigger(props)}
						<Button {...props} variant="danger">Delete graph</Button>
					{/snippet}
					{#snippet footer()}
						<Button onclick={() => (dialogOpen = false)}>Keep graph</Button>
						<Button variant="danger" onclick={() => (dialogOpen = false)}>Delete graph</Button>
					{/snippet}
				</Dialog>
			</div>
		</Card>
	</div>

	<Card title="Tabs">
		<Tabs
			label="Example tabs"
			bind:value={tab}
			items={[
				{ value: 'answer', label: 'Answer' },
				{ value: 'path', label: 'Graph path' },
				{ value: 'empty', label: 'Empty state' }
			]}
		>
			{#snippet panel(v)}
				{#if v === 'answer'}
					<CitedAnswer answer={featuredAnswer} />
				{:else if v === 'path'}
					<GraphPath steps={featuredAnswer.path} />
				{:else}
					<EmptyState
						title="No answers yet"
						description="Answers appear here when you or an agent ask the brain a question. Each one shows its sources and graph path."
					>
						{#snippet icon()}<Inbox />{/snippet}
						{#snippet action()}<Button variant="primary">Ask a question</Button>{/snippet}
					</EmptyState>
				{/if}
			{/snippet}
		</Tabs>
	</Card>

	<div class="two">
		<Card title="Rows">
			<EntityRow name="Alice Kim" type="person" meta="identity, 2 PRs" value={3} valueLabel="reviews" selected />
			<EntityRow name="payments" type="team" meta="2 people, 1 system" />
			<EntityRow name="Billing" type="system" meta="services/billing/**" value={8} valueLabel="changes" />
			<WorkItemRow item={recentWork[0]} />
			<WorkItemRow item={recentWork[1]} />
			<WorkItemRow item={recentWork[3]} />
		</Card>
		<Card title="Stat and bars">
			<div class="stack">
				<dl class="row stats">
					<Stat type="work-item" label="Work items" value={15} note="4 open" />
					<Stat type="change" label="Changes" value={25} />
					<Stat label="Sources" value={3} />
				</dl>
				<ActivityBars
					unit="changes"
					items={[
						{ label: 'Auth', value: 9, meta: 'identity' },
						{ label: 'Billing', value: 8, meta: 'payments' },
						{ label: 'Infra', value: 3, meta: 'unowned' }
					]}
				/>
			</div>
		</Card>
	</div>
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}
	h1 {
		font-size: var(--text-2xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
	}
	header p {
		margin-top: var(--space-1);
		color: var(--color-text-muted);
		max-width: 70ch;
	}
	.sub {
		margin: var(--space-5) 0 var(--space-3);
		font-size: var(--text-sm);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.two {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
		gap: var(--space-5);
		align-items: start;
	}
	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.stats {
		gap: var(--space-8);
		margin: 0;
	}
	.swatches {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
		gap: var(--space-4);
	}
	.swatch {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--text-sm);
	}
	.swatch span {
		height: 3rem;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-1);
	}
	.swatch code {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.scale {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.scale li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-1) var(--space-4);
	}
	.scale span {
		line-height: var(--leading-tight);
		min-width: 0;
	}
	.scale small {
		color: var(--color-text-muted);
	}
	.widths {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-6);
	}
	.w {
		font-size: var(--text-xl);
		font-weight: var(--weight-bold);
	}
</style>
