<!-- Living gallery of the design system: every component and its states. Keep it in sync. -->
<script lang="ts">
	import { CloudOff, Inbox, LoaderCircle, Plus, Search, Trash2 } from '@lucide/svelte';
	import {
		AnswerRating,
		ActivityBars,
		AddCompanyDialog,
		Avatar,
		Badge,
		Banner,
		BuildProgress,
		Button,
		Card,
		Checkbox,
		ChoiceCard,
		CitedAnswer,
		CompanyForm,
		CompanyRail,
		ConfigPreview,
		Dialog,
		EmptyState,
		EntityRow,
		GraphPath,
		GraphWalk,
		Input,
		Menu,
		NodeChip,
		NodeInspector,
		Select,
		SourceCard,
		Stat,
		Stepper,
		Tabs,
		TagInput,
		TerritoryMap,
		Tooltip,
		WalkAnswer,
		WalkSteps,
		WorkItemRow
	} from '$lib';
	import { AddCompany, type Lookup } from '$lib/addCompany.svelte';
	import { layoutMap, neighbourhood } from '$lib/graph';
	import { RepoChecks, type RepoResult } from '$lib/repochecks.svelte';
	import * as builds from './build-samples';
	import { syntheticGraph } from './graph-samples';
	import * as walks from './walk-samples';
	import { highlightFor } from '$lib/walk';
	import {
		NODE_LABELS,
		type CitedAnswer as Answer,
		type Company,
		type CompanyConfig,
		type CompanyStatus,
		type NodeType,
		type RepoLookup,
		type SourceConfig,
		type WorkItem
	} from '$lib/types';

	// The Ask walk: citation 1 stays lit unless another is hovered.
	let walkHover = $state<number | null>(null);
	let liveRating = $state<'up' | 'down' | null>(null);
	let liveNote = $state<string | null>(null);
	const walkActive = $derived(walkHover ?? 1);
	const walkLit = $derived(highlightFor(walks.answer.sources[walkActive - 1], walks.done));
	const walkCites = new Map(walks.answer.sources.map((s, i) => [s.uid, [i + 1]]));

	// Example content for the gallery, taken from apps/backend/examples/synthetic_company.
	const featuredAnswer: Answer = {
		question: 'Why did we replace sessions with JWTs?',
		parts: [
			{
				text: 'Alice replaced server-side sessions with short-lived JWTs because the session table was the main source of database load',
				cite: [1, 2]
			},
			{ text: '. Refresh tokens stay server-side', cite: [3] },
			{ text: '.' }
		],
		path: [
			{ node: { uid: 'person:alice', type: 'person', label: 'alice' }, edge: 'AUTHORED' },
			{ node: { uid: 'synthetic:pr:1', type: 'work-item', label: 'PR #1' }, edge: 'CLOSES' },
			{ node: { uid: 'synthetic:issue:11', type: 'work-item', label: 'Issue #11' }, edge: 'TOUCHES' },
			{ node: { uid: 'system:Auth', type: 'system', label: 'Auth' } }
		],
		sources: [
			{
				uid: 'synthetic:pr:1',
				title: 'feat(auth): switch sessions to JWT',
				meta: 'PR #1, merged 6 Feb by alice',
				url: 'https://example.com/synthetic/app/pull/1'
			},
			{
				uid: 'synthetic:issue:11',
				title: 'Session table causes DB load spikes',
				meta: 'Issue #11, closed 6 Feb'
			},
			{
				uid: 'synthetic:doc:docs/auth-design.md',
				title: 'Auth design',
				meta: 'docs/auth-design.md'
			}
		]
	};
	const recentWork: WorkItem[] = [
		{ uid: 'synthetic:issue:14', kind: 'issue', number: 14, title: 'Invoice emails sometimes sent twice', state: 'open', author: 'erin', date: '2026-09-10', system: 'Billing' },
		{ uid: 'synthetic:pr:10', kind: 'pull_request', number: 10, title: 'refactor(auth): extract token service', state: 'merged', author: 'carol', date: '2026-09-01', system: 'Auth' },
		{ uid: 'synthetic:slack:thread:eng-2026-07-15', kind: 'thread', title: '#eng: should billing own the checkout page?', state: 'open', author: 'bob', date: '2026-07-15' },
		{ uid: 'synthetic:ticket:7', kind: 'ticket', number: 7, title: 'Ticket with no author, date or system', state: 'done' }
	];
	const longError =
		'fetch failed for github:FalkorDB/FalkorDB: GraphQL returned 502 after 5 retries; the partial clone under data/raw/falkordb/github/clone was left in place and the next build resumes from its last completed run';

	const company = (name: string, status: CompanyStatus = 'ready'): Company => ({
		slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '_'),
		name,
		data_permission: status === 'invalid' ? null : 'public',
		status,
		last_synced_at: null,
		error: null,
		build: null,
		graph_reachable: status !== 'unknown'
	});
	const railThree = ['Acme Labs', 'FalkorDB', 'Synthetic Co'].map((n) => company(n));
	const railStatus = [
		company('Acme Labs'),
		company('Building Co', 'building'),
		company('Current Co'),
		company('Empty Co', 'empty'),
		company('Failed Co', 'failed'),
		company('Invalid Co', 'invalid'),
		company('Offline Co', 'unknown')
	];
	const railMany = Array.from({ length: 12 }, (_, i) => company(`Company ${i + 1}`));
	const railEdge = [
		company('FalkorDB'),
		company('Fabric'),
		company('The Very Long Named Company Holdings Ltd')
	];
	// The rail renders real links; in the gallery a click must not leave the page.
	const stay = (e: MouseEvent) => {
		if ((e.target as Element).closest('a')) e.preventDefault();
	};
	const nodeTypes = Object.keys(NODE_LABELS) as NodeType[];
	let dialogOpen = $state(false);
	let sort = $state('recent');
	let name = $state('');
	let tab = $state('answer');

	let permission = $state('public');
	let permissionDisabled = $state('own');
	let agree = $state(true);
	let agreeOff = $state(false);
	let level = $state('engineer');
	let levelEmpty = $state('');
	let levelLong = $state('long');
	/** Fixed answers for the source cards: no calls to the API from the gallery. */
	class FixedChecks extends RepoChecks {
		constructor(token: 'env' | 'gh' | null, results: Record<string, RepoResult> = {}) {
			super();
			this.token = token;
			for (const [repo, result] of Object.entries(results)) this.results.set(repo, result);
		}
		override async checkToken() {}
		override check() {
			return Promise.resolve();
		}
	}
	/** The add-company dialog in one fixed state: typing never calls the API from the gallery. */
	class FixedAdd extends AddCompany {
		constructor(text: string, lookup: Lookup | null = null) {
			super();
			this.text = text;
			if (lookup) this.result = { repo: this.repo ?? '', lookup };
		}
		override input(text: string) {
			this.text = text;
		}
		override async retry() {}
		override async create() {
			return null;
		}
		override async addTo() {
			return null;
		}
	}
	const repoLookup = (over: Partial<RepoLookup> = {}): Lookup => ({
		kind: 'found',
		lookup: {
			repo: 'acme-labs/platform',
			exists: true,
			private: false,
			owner_name: 'Acme Labs',
			name: 'Acme Labs',
			slug: 'acme_labs',
			since: '2025-10-16',
			company: null,
			owner_company: null,
			...over
		}
	});
	const addStates: { label: string; ctl: FixedAdd }[] = [
		{ label: 'Empty', ctl: new FixedAdd('') },
		{ label: 'Typing', ctl: new FixedAdd('acme-labs') },
		{ label: 'Checking', ctl: new FixedAdd('acme-labs/platform', { kind: 'checking' }) },
		{ label: 'Ready', ctl: new FixedAdd('https://github.com/acme-labs/platform', repoLookup()) },
		{
			label: 'Owner has a brain',
			ctl: new FixedAdd(
				'FalkorDB/falkordb-py',
				repoLookup({
					repo: 'FalkorDB/falkordb-py',
					name: 'FalkorDB falkordb-py',
					slug: 'falkordb_py',
					owner_company: { slug: 'falkordb', name: 'FalkorDB' }
				})
			)
		},
		{
			label: 'Already read',
			ctl: new FixedAdd(
				'FalkorDB/FalkorDB',
				repoLookup({ repo: 'FalkorDB/FalkorDB', company: { slug: 'falkordb', name: 'FalkorDB' } })
			)
		},
		{
			label: 'Private',
			ctl: new FixedAdd('acme-labs/billing', { kind: 'private', repo: 'acme-labs/billing' })
		},
		{
			label: 'Not found',
			ctl: new FixedAdd('acme-labs/platfrom', { kind: 'missing', repo: 'acme-labs/platfrom' })
		},
		{ label: 'No token', ctl: new FixedAdd('acme-labs/platform', { kind: 'no_token' }) },
		{ label: 'GitHub down', ctl: new FixedAdd('acme-labs/platform', { kind: 'unreachable' }) },
		{
			label: 'Long name',
			ctl: new FixedAdd(
				'the-international-consortium-of-very-long-organisation-names/a-repository-with-an-equally-long-name',
				repoLookup({
					name: 'The International Consortium of Very Long Organisation Names and Friends',
					slug: 'the_international_consortium_of_very_long_organisation_names'
				})
			)
		}
	];

	const checksFound = new FixedChecks('env', { 'acme-labs/platform': { kind: 'found', private: false } });
	const checksNoToken = new FixedChecks(null);
	const checksPrivate = new FixedChecks('gh', { 'acme-labs/secret': { kind: 'found', private: true } });
	const checksMissing = new FixedChecks('env', {
		'acme-labs/typo': { kind: 'missing' },
		'acme-labs/slow': { kind: 'rate_limited' }
	});
	const github = (repo: string): SourceConfig => ({
		type: 'github',
		repo,
		include: ['commits', 'pull_requests', 'issues', 'reviews', 'codeowners', 'repo_docs']
	});
	let srcFound = $state(github('acme-labs/platform'));
	let srcNoToken = $state(github('acme-labs/platform'));
	let srcPrivate = $state(github('acme-labs/secret'));
	let srcMissing = $state(github('acme-labs/typo'));
	let srcSlow = $state(github('acme-labs/slow'));
	let srcInvalid = $state<SourceConfig>({ type: 'github', repo: 'platform', include: ['commits'] });
	let srcDocs = $state<SourceConfig>({ type: 'local_docs', path: 'data/inbox/acme_labs/docs' });
	let srcJsonl = $state<SourceConfig>({ type: 'canonical_jsonl', path: '' });
	const previewYaml = [
		'slug: acme_labs',
		'name: Acme Labs',
		'data_permission: own',
		'window:',
		'  since: 2026-04-15',
		'sources:',
		'  - type: github',
		'    repo: acme-labs/platform',
		'    include: [commits, pull_requests, issues, reviews, codeowners, repo_docs]',
		'  - type: local_docs',
		'    path: data/inbox/acme_labs/docs',
		'systems:',
		'  rules:',
		'    - { match: "services/auth/**", system: "Auth" }',
		'  fallback: depth_2',
		'  ignore: ["**/*.{lock,min.js}"]',
		'people:',
		'  bots: ["dependabot[bot]"]',
		'  aliases: {}',
		''
	].join('\n');
	const noop = () => {};
	// CompanyForm drafts. Local-folder sources only, so the gallery never asks GitHub anything.
	const formDraft = (over: Partial<CompanyConfig> = {}): CompanyConfig => ({
		slug: 'acme_labs',
		name: 'Acme Labs',
		data_permission: 'own',
		window: { since: '2026-04-15' },
		sources: [{ type: 'local_docs', path: 'data/inbox/acme_labs/docs' }],
		systems: {
			rules: [{ match: 'services/auth/**', system: 'Auth' }],
			fallback: 'depth_2',
			ignore: ['**/*.lock']
		},
		people: { bots: ['dependabot[bot]'], aliases: { 'A. Lee': 'alice' } },
		...over
	});
	let formNew = $state<CompanyConfig>({
		slug: '',
		name: '',
		data_permission: 'public',
		window: { since: '2025-10-16' },
		sources: [],
		systems: { rules: [], fallback: 'depth_2', ignore: [] },
		people: { bots: [], aliases: {} }
	});
	let formErrors = $state<CompanyConfig>(formDraft({ window: { since: '2026-13-45' } }));
	let formLocked = $state<CompanyConfig>(formDraft());
	// A hand-edited config can hold the same tag twice; Settings must still open and edit it.
	let formAll = $state<CompanyConfig>(
		formDraft({
			systems: {
				rules: [{ match: 'services/auth/**', system: 'Auth' }],
				fallback: 'depth_2',
				ignore: ['**/*.lock', '**/*.lock', 'dist/**']
			},
			people: { bots: ['dependabot[bot]', 'dependabot[bot]'], aliases: {} }
		})
	);
	const formErrorList = [
		{ loc: ['slug'], msg: 'acme_labs is already a company. Pick another name' },
		{ loc: ['name'], msg: 'Name is required' },
		{ loc: ['window', 'since'], msg: 'Enter a date like 2026-04-15' }
	];
	let globs = $state<string[]>(['apps/web/**', 'services/billing/**']);
	let logins = $state<string[]>([]);
	let dupes = $state<string[]>(['*.lock', '*.lock', 'dist/**']);
	let aliases = $state<string[]>([
		'dependabot[bot]',
		'a-very-long-login-that-would-not-fit-on-one-line-without-wrapping-inside-the-field-xyz'
	]);
	const steps = [
		{ label: 'Company', hint: 'Name and slug' },
		{ label: 'Sources', hint: 'Where to read' },
		{ label: 'Rules', hint: 'Systems and bots' },
		{ label: 'Build' }
	];
	const levels = [
		{ value: 'engineer', label: 'Engineer' },
		{ value: 'lead', label: 'Engineering lead' },
		{ value: 'long', label: 'A very long option label that has to wrap in the list and truncate on the closed field' }
	];

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

	// The graph map and inspector, on the synthetic company's real graph view.
	const mapLayout = layoutMap(syntheticGraph, { ticks: 300 });
	let mapSelected = $state<string | null>('person:alice');
	const graphNode = (uid: string) => syntheticGraph.nodes.find((n) => n.uid === uid);
	const territoryOf = (uid: string) =>
		syntheticGraph.territories.find((t) => t.id === graphNode(uid)?.territory) ?? null;
	const alice = graphNode('person:alice')!;
	const ciBot = graphNode('person:ci-bot')!;
	const longPr = syntheticGraph.nodes
		.filter((n) => n.label === 'WorkItem')
		.toSorted((a, b) => (b.title ?? '').length - (a.title ?? '').length)[0];
	const aliceEntity = {
		uid: 'person:alice',
		label: 'Person',
		title: 'alice',
		kind: null,
		state: null,
		url: null,
		date: null,
		body: '',
		neighbour_count: neighbourhood(syntheticGraph, 'person:alice').uids.size - 1
	};
</script>

<svelte:head><title>Components | Citadel</title></svelte:head>

<div class="page">
	<header>
		<h1>Components</h1>
		<p>
			Wide type and a calm body. Rules are in <code>apps/frontend/design-system.md</code>.
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

	<Card title="Banner">
		<p class="note">
			The state of a whole view, with the one thing to do about it. The icon and the title say
			the state, so colour is never the only signal. Long text wraps and never scrolls sideways.
		</p>
		<div class="stack">
			<Banner tone="warning" title="Building, step 2 of 5" icon={LoaderCircle} spin>
				{#snippet action()}<Button>See progress</Button>{/snippet}
			</Banner>
			<Banner tone="danger" title="Last build failed">
				{longError}
				{#snippet action()}<Button>See details</Button>{/snippet}
			</Banner>
			<Banner tone="neutral" title="Graph unreachable" icon={CloudOff}>
				Citadel can't reach FalkorDB, so counts and answers are unavailable. Start it with
				<code>make up</code>.
			</Banner>
			<Banner tone="danger" title="Config invalid">sources.0.repo: field required</Banner>
		</div>
	</Card>

	<div class="two">
		<Card title="Input">
			<div class="stack">
				<Input label="Company name" placeholder="Acme Inc" hint="Shown in the top bar" bind:value={name} />
				<Input label="Slug" value="acme inc" error="Use lowercase letters, digits and dashes only" />
				<Input label="Graph name" prefix="brain_" value="acme_labs" hint="Fixed text before the value" />
				<Input label="Repository" prefix="github.com/" placeholder="owner/name" error="Repo must look like 'owner/name'" />
				<Input label="Folder" mono value="data/inbox/acme_labs/docs" />
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

	<Card title="Stepper">
		<p class="note">
			The steps of a flow. The current step is the one solid accent block; finished steps show
			a check in an ink circle and say "done" to screen readers.
		</p>
		<div class="stack">
			<Stepper {steps} current={0} done={[]} />
			<Stepper {steps} current={2} done={[0, 1]} />
			<Stepper
				steps={[
					{ label: 'A step with a long name that wraps instead of overflowing', hint: 'And a long hint too' },
					{ label: 'Next' }
				]}
				current={1}
				done={[0]}
			/>
		</div>
	</Card>

	<div class="two">
		<Card title="Select">
			<div class="stack">
				<Select label="Role" bind:value={level} options={levels} hint="Hover, focus, or open it and use the arrow keys" />
				<Select label="Nothing chosen" bind:value={levelEmpty} options={levels} placeholder="Choose a role" />
				<Select label="Role" value="lead" options={levels} disabled hint="Disabled" />
				<Select label="Role" value="" options={levels} error="Pick a role to continue" />
				<Select label="Long option" bind:value={levelLong} options={levels} />
			</div>
		</Card>

		<Card title="Tag input">
			<div class="stack">
				<TagInput
					label="Paths"
					bind:values={globs}
					mono
					placeholder="apps/web/**"
					hint="Enter or a comma adds. Paste a, b to add both."
				/>
				<TagInput label="Logins" bind:values={logins} placeholder="Type a login" />
				<TagInput label="Bot aliases" bind:values={aliases} mono />
				<TagInput label="Paths" values={['docs/**']} disabled hint="Disabled" />
				<TagInput label="Paths" values={[]} error="Add at least one path" mono />
				<TagInput label="Paths" bind:values={dupes} mono hint="The same tag twice, as a hand-edited file can hold it" />
			</div>
		</Card>
	</div>

	<div class="two">
		<Card title="Choice card">
			<fieldset class="choices">
				<legend>Data permission</legend>
				<ChoiceCard name="gallery-permission" value="public" bind:group={permission} title="Public data" description="Read public repositories only." />
				<ChoiceCard name="gallery-permission" value="own" bind:group={permission} title="Our own data" description="Private repositories and tickets we own." />
				<ChoiceCard name="gallery-permission" value="long" bind:group={permission} title="A title that is long enough to wrap onto a second line in a narrow card" description="And a description with a-very-long-unbroken-token-that-must-wrap-instead-of-overflowing-the-card." />
			</fieldset>
			<fieldset class="choices">
				<legend>Disabled</legend>
				<ChoiceCard name="gallery-permission-off" value="public" bind:group={permissionDisabled} title="Public data" description="Not available." disabled />
				<ChoiceCard name="gallery-permission-off" value="own" bind:group={permissionDisabled} title="Our own data" description="Selected and locked." disabled />
			</fieldset>
		</Card>

		<Card title="Checkbox">
			<div class="stack">
				<Checkbox label="Include closed pull requests" bind:checked={agree} />
				<Checkbox label="Unchecked" bind:checked={agreeOff} />
				<Checkbox label="Disabled and checked" checked disabled />
				<Checkbox label="Disabled" checked={false} disabled />
				<Checkbox
					label="A long label that has to wrap onto several lines without pushing the box out of line or scrolling the page sideways, even with-a-very-long-unbroken-token"
					checked={false}
				/>
			</div>
		</Card>
	</div>

	<Card title="Add-company dialog">
		<p class="note">
			The rail's + opens it: one field for a public GitHub repository, then what Citadel will make.
			Each button opens one state; typing here never calls the API.
		</p>
		<div class="row">
			{#each addStates as state (state.label)}
				<Button size="sm" onclick={() => (state.ctl.open = true)}>{state.label}</Button>
				<AddCompanyDialog ctl={state.ctl} />
			{/each}
		</div>
	</Card>

	<Card title="Source card">
		<p class="note">
			One card per source in the add-company form. GitHub: the repository, what to read, and what
			GitHub said about it (found, rate limited), a note when no token exists, and an error when
			GitHub cannot find the repository or when it is private while the data permission is not Own. Folder sources take one
			path.
		</p>
		<div class="sources">
			<SourceCard bind:source={srcFound} index={0} dataPermission="public" errors={[]} onremove={noop} checks={checksFound} />
			<SourceCard bind:source={srcNoToken} index={1} dataPermission="public" errors={[]} onremove={noop} checks={checksNoToken} />
			<SourceCard bind:source={srcPrivate} index={2} dataPermission="public" errors={[]} onremove={noop} checks={checksPrivate} />
			<SourceCard bind:source={srcMissing} index={3} dataPermission="own" errors={[]} onremove={noop} checks={checksMissing} />
			<SourceCard bind:source={srcSlow} index={4} dataPermission="own" errors={[]} onremove={noop} checks={checksMissing} />
			<SourceCard
				bind:source={srcInvalid}
				index={5}
				dataPermission="public"
				errors={[{ loc: ['sources', 5, 'repo'], msg: "Value error, repo must look like 'owner/name'" }]}
				onremove={noop}
				checks={checksFound}
			/>
			<SourceCard bind:source={srcDocs} index={6} dataPermission="own" errors={[]} onremove={noop} checks={checksFound} />
			<SourceCard
				bind:source={srcJsonl}
				index={7}
				dataPermission="own"
				errors={[{ loc: ['sources', 7, 'type'], msg: 'unknown source type' }]}
				onremove={noop}
				checks={checksFound}
			/>
		</div>
	</Card>

	<Card title="Company form">
		<p class="note">
			The fields of a company file. One step at a time in the add-company wizard (company,
			sources, rules) and all three on one page in Settings, where the graph name is read-only.
			Errors show under their field; the form never calls the API. The last form holds duplicate
			tags, as a hand-edited file can.
		</p>
		<div class="forms">
			<figure>
				<CompanyForm bind:draft={formNew} section="company" errors={[]} />
				<figcaption>Company step, empty</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formErrors} section="company" errors={formErrorList} />
				<figcaption>Company step, with errors</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formLocked} section="company" errors={[]} slugLocked />
				<figcaption>Company step, graph name locked (an existing company)</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formAll} section="all" errors={[]} slugLocked />
				<figcaption>All sections, as in Settings</figcaption>
			</figure>
		</div>
	</Card>

	<div class="two">
		<Card title="Config preview">
			<p class="note">Blocks the current step adds are marked with a bar, a tint and a line of words.</p>
			<ConfigPreview yaml={previewYaml} highlight={['sources']} />
		</Card>
		<Card title="Config preview, other states">
			<div class="stack">
				<ConfigPreview yaml={previewYaml.split('systems:')[0]} highlight={['slug', 'name', 'data_permission', 'window']} stale />
				<ConfigPreview yaml="" highlight={[]} />
			</div>
		</Card>
	</div>

	<Card title="Company rail">
		<p class="note">
			One tile per company. The current one is ink with a bar on its edge; building, failed,
			invalid and unreachable graphs carry a mark and a word in the accessible name. Hover or
			focus a tile for its name and graph.
		</p>
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
		<div class="rails" onclick={stay}>
			<figure>
				<div class="frame"><CompanyRail companies={railThree} current="falkordb" pathname="/components" /></div>
				<figcaption>Three companies</figcaption>
			</figure>
			<figure>
				<div class="frame"><CompanyRail companies={railStatus} current="current_co" pathname="/components" /></div>
				<figcaption>Building, failed, invalid, unreachable</figcaption>
			</figure>
			<figure>
				<div class="frame"><CompanyRail companies={railMany} current="company_9" pathname="/components" /></div>
				<figcaption>Twelve companies, list scrolls</figcaption>
			</figure>
			<figure>
				<div class="frame"><CompanyRail companies={railEdge} current={null} pathname="/components" /></div>
				<figcaption>Colliding monogram, 40-character name</figcaption>
			</figure>
		</div>
	</Card>

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

	<Card title="Graph walk, steps and answer (Ask)">
		<div class="walks">
			<figure>
				<GraphWalk steps={walks.running} fresh={null} />
				<WalkSteps steps={walks.running} />
				<figcaption>Running: step 2 asked for, step 1 drawn</figcaption>
			</figure>
			<figure>
				<GraphWalk
					steps={walks.done}
					highlight={walkLit}
					cited={new Set(walks.answer.sources.map((s) => s.uid))}
				/>
				<WalkSteps
					steps={walks.done}
					open="s3"
					ontoggle={() => {}}
					cites={walkCites}
					active={walkActive}
				/>
				<figcaption>Done: citation 1 lit, step 3 open with its rows</figcaption>
			</figure>
			<figure>
				<WalkAnswer answer={walks.answer} active={walkActive} onactive={(n) => (walkHover = n)} />
				<figcaption>Answer: hover a chip or a source</figcaption>
			</figure>
			<figure>
				<WalkSteps steps={walks.rough} />
				<GraphWalk steps={[]} />
				<WalkAnswer answer={walks.stopped} />
				<WalkAnswer answer={walks.refused} />
				<figcaption>A failed call, an empty call, a rejected check; empty stage; no answer</figcaption>
			</figure>
		</div>
	</Card>

	<Card title="Answer rating (Ask)">
		<div class="walks">
			<figure>
				<AnswerRating
					rating={liveRating}
					note={liveNote}
					onrate={(r) => {
						liveRating = r;
						liveNote = null;
					}}
					onnote={(text) => (liveNote = text)}
				/>
				<figcaption>Live: press a thumb, press it again to take it back; thumbs down asks for a note</figcaption>
			</figure>
			<figure>
				<AnswerRating rating="up" status="saved" />
				<figcaption>Marked right</figcaption>
			</figure>
			<figure>
				<AnswerRating rating="down" status="saved" />
				<figcaption>Marked wrong, note not sent yet</figcaption>
			</figure>
			<figure>
				<AnswerRating
					rating="down"
					status="saved"
					note="It named bob, but erin has reviewed every Billing change since March and bob moved to the platform team."
				/>
				<figcaption>Marked wrong with a long note</figcaption>
			</figure>
			<figure>
				<AnswerRating rating="up" status="saving" />
				<figcaption>Saving</figcaption>
			</figure>
			<figure>
				<AnswerRating rating={null} status="failed" />
				<figcaption>The save failed: the thumbs that was there stays</figcaption>
			</figure>
		</div>
	</Card>

	<div class="two">
		<Card title="Rows">
			<EntityRow name="Alice Kim" type="person" meta="identity, 2 PRs" value={3} valueLabel="reviews" selected />
			<EntityRow name="payments" type="team" meta="2 people, 1 system" />
			<EntityRow name="Billing" type="system" meta="services/billing/**" value={8} valueLabel="changes" />
			<WorkItemRow item={recentWork[0]} />
			<WorkItemRow item={recentWork[1]} />
			<WorkItemRow item={recentWork[2]} />
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

	<Card title="Build progress">
		<p class="note">
			One build: the step it is on, a meter, a cell per source and stage, and the log. Every
			cell pairs an icon with a word. The buttons are passed in by the page.
		</p>
		<div class="stack">
			<h3 class="sub">Running</h3>
			<BuildProgress snapshot={builds.running}>
				{#snippet actions()}
					<Button variant="ghost">Stop build</Button>
					<Button variant="primary">Go to Acme Labs</Button>
				{/snippet}
			</BuildProgress>
			<h3 class="sub">Stopping, queued and a skipped source</h3>
			<BuildProgress snapshot={builds.running} stopping />
			<BuildProgress snapshot={builds.queued} />
			<BuildProgress snapshot={builds.skippedSource} />
			<h3 class="sub">Rebuild</h3>
			<BuildProgress snapshot={builds.rebuild} />
			<h3 class="sub">Done</h3>
			<BuildProgress snapshot={builds.done}>
				{#snippet actions()}
					<span></span>
					<Button variant="primary">Go to Acme Labs</Button>
				{/snippet}
			</BuildProgress>
			<h3 class="sub">Failed</h3>
			<BuildProgress snapshot={builds.failed}>
				{#snippet actions()}
					<Button>Go to Acme Labs</Button>
					<Button variant="primary">Retry build</Button>
				{/snippet}
			</BuildProgress>
			<h3 class="sub">Stopped between sources</h3>
			<BuildProgress snapshot={builds.stopped} />
		</div>
	</Card>

	<Card title="Territory map">
		<p class="note">
			The Graph page's map: one tonal territory per system, ink routes between them, a selection
			lights its neighbours and outlines the territories it reaches. Click a node, drag, use the
			buttons or pinch to zoom (scroll zooms on the Graph page). Synthetic company, bots shown.
		</p>
		<div class="map-sample">
			<TerritoryMap
				view={syntheticGraph}
				layout={mapLayout}
				selected={mapSelected}
				onselect={(uid) => (mapSelected = uid)}
				scrollZoom={false}
			/>
		</div>
		<h3 class="sub">Nothing selected</h3>
		<div class="map-sample short">
			<TerritoryMap view={syntheticGraph} layout={mapLayout} scrollZoom={false} />
		</div>
	</Card>

	<Card title="Node inspector">
		<p class="note">
			What the Graph page says about a selected node. Counts come from the links the map draws;
			fields come from <code>get_entity</code>.
		</p>
		<div class="inspectors">
			<div>
				<h3 class="sub">Fields read</h3>
				<NodeInspector
					node={alice}
					hood={neighbourhood(syntheticGraph, alice.uid)}
					territory={territoryOf(alice.uid)}
					entity={aliceEntity}
					lookup={graphNode}
				/>
			</div>
			<div>
				<h3 class="sub">Reading fields, long title</h3>
				<NodeInspector
					node={longPr}
					hood={neighbourhood(syntheticGraph, longPr.uid)}
					territory={territoryOf(longPr.uid)}
					lookup={graphNode}
				/>
			</div>
			<div>
				<h3 class="sub">A bot, fields failed</h3>
				<NodeInspector
					node={ciBot}
					hood={neighbourhood(syntheticGraph, ciBot.uid)}
					territory={territoryOf(ciBot.uid)}
					error="FalkorDB is not reachable"
					lookup={graphNode}
				/>
			</div>
		</div>
	</Card>
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
	.map-sample {
		height: 30rem;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.map-sample.short {
		height: 18rem;
	}
	.inspectors {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
		gap: var(--space-5);
		align-items: start;
	}
	.inspectors > div > :global(.inspector) {
		height: auto;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.forms {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr));
		gap: var(--space-6);
		align-items: start;
	}
	.forms figure {
		margin: 0;
		min-width: 0;
	}
	.forms figcaption {
		margin-top: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.sources {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(22rem, 100%), 1fr));
		gap: var(--space-4);
		margin-top: var(--space-4);
	}
	.two {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr));
		gap: var(--space-5);
		align-items: start;
	}
	.walks {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 28rem), 1fr));
		gap: var(--space-6);
		align-items: start;
	}
	.walks figure {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
	}
	.note {
		max-width: 70ch;
		margin-bottom: var(--space-4);
		color: var(--color-text-muted);
	}
	.rails {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-8);
	}
	.rails figure {
		margin: 0;
	}
	.rails figcaption {
		max-width: 10rem;
		margin-top: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.frame {
		width: fit-content;
		height: 26rem;
		border: var(--border-hair) solid var(--color-line);
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
	.choices {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
		gap: var(--space-3);
		margin: 0 0 var(--space-4);
		padding: 0;
		border: 0;
	}
	.choices legend {
		padding: 0;
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
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
