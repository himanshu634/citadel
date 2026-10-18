<!-- Living gallery of the design system: every component and its states. Keep it in sync. -->
<script lang="ts">
	import { CloudOff, Inbox, LoaderCircle, Plus, Search, Trash2 } from '@lucide/svelte';
	import {
		AnswerRating,
		ActivityBars,
		AddCompanyDialog,
		AskLane,
		Avatar,
		Badge,
		Banner,
		BuildProgress,
		Button,
		Card,
		Checkbox,
		ChoiceCard,
		AgentRun,
		ChatList,
		CitedAnswer,
		ClaimApproval,
		CompanyForm,
		CompanyRail,
		ConfigPreview,
		Dialog,
		EmptyState,
		EntityRow,
		GraphPath,
		GraphWalk,
		Input,
		KeeperLog,
		KeeperTrail,
		Menu,
		ModelPicker,
		NodeChip,
		NodeInspector,
		RefLink,
		RefText,
		Select,
		SourceCard,
		SourceRow,
		Splitter,
		Stat,
		StepRows,
		Stepper,
		Tabs,
		TagInput,
		TerritoryMap,
		Tooltip,
		TurnTimeline,
		WalkAnswer,
		WalkLedger,
		WalkSteps,
		WorkItemRow
	} from '$lib';
	import { AddCompany, type Lookup } from '$lib/addCompany.svelte';
	import { layoutMap, neighbourhood } from '$lib/graph';
	import { RepoChecks, type RepoResult } from '$lib/repochecks.svelte';
	import * as builds from './build-samples';
	import { syntheticGraph } from './graph-samples';
	import { archivistRun, doneRun, failedRun, runningRun } from './activity-samples';
	import * as keeper from './keeper-samples';
	import { evidenceRefs } from '$lib/keeper';
	const galleryRefs = (uids: string[]) => evidenceRefs(uids, () => null);
	import { doingNow, hereLabel, trailOf } from '$lib/activity';
	import * as walks from './walk-samples';
	import * as chatSamples from './chat-samples';
	import * as sourceSamples from './source-samples';
	import { answerRefs, carryOver, highlightFor } from '$lib/walk';
	import { refContext, textRuns } from '$lib/links';
	import { WALK_LIMITS, clampSize } from '$lib/splitter';
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
	let liveModel = $state('claude-sonnet-5-5');
	let liveNote = $state<string | null>(null);
	const walkActive = $derived(walkHover ?? 1);
	const walkLit = $derived(highlightFor(walks.answer.sources[walkActive - 1], walks.done));
	const walkCites = new Map(walks.answer.sources.map((s, i) => [s.uid, [i + 1]]));
	let ledgerOpen = $state<string | null>('s3');
	const carried = carryOver(walks.done, walks.followUp);

	// A splitter between two boxes: the same columns as the Ask page's lanes.
	let splitBox = $state<HTMLElement>();
	let splitWidth = $state(0);
	let splitRight = $state(0);
	let splitSize = $state(WALK_LIMITS.reset);
	let splitFolded = $state(false);
	const measureSplit = () => {
		if (splitBox) splitRight = splitBox.getBoundingClientRect().right;
	};
	$effect(() => {
		void splitWidth;
		measureSplit();
	});
	const splitPane = $derived(
		splitFolded ? 'var(--walk-strip)' : `${Math.round(clampSize(splitSize, splitWidth) * splitWidth)}px`
	);

	// Example content for the gallery, taken from apps/brain/examples/synthetic_company.
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
	// References: the walk saw PR #1 and #10 (example.com urls); the repo makes the rest GitHub links.
	const refRepo = refContext([], ['acme/app']);
	const refAnswer = {
		...walks.answer,
		text: 'Sessions moved to JWT in #1 and the token code left the monolith in #10 [1]. The check lives in `services/auth/token.py:42`; see `docs/auth-design.md` and #23 for what is left. `identity` owns it.'
	};
	const refAnswerRefs = answerRefs(walks.done, walks.answer.sources, ['acme/app']);

	const recentWork: WorkItem[] = [
		{ uid: 'synthetic:issue:14', kind: 'issue', number: 14, title: 'Invoice emails sometimes sent twice', state: 'open', author: 'erin', date: '2026-09-10', system: 'Billing', url: 'https://example.com/synthetic/app/issues/14' },
		{ uid: 'synthetic:pr:10', kind: 'pull_request', number: 10, title: 'refactor(auth): extract token service', state: 'merged', author: 'carol', date: '2026-09-01', system: 'Auth', url: 'https://example.com/synthetic/app/pull/10' },
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
	let srcLinear = $state<SourceConfig>({ type: 'linear', workspace: 'synthetic-co', teams: ['IDN', 'PAY'] });
	let srcLinearEmpty = $state<SourceConfig>({ type: 'linear', workspace: '', teams: [] });
	let srcLinearBad = $state<SourceConfig>({ type: 'linear', workspace: 'Synthetic Co', teams: ['IDN', 'PAY-1', '9OPS'] });
	const linearBadErrors = [
		{ loc: ['sources', 10, 'workspace'], msg: "String should match pattern '^[a-z0-9-]+$'" },
		{ loc: ['sources', 10, 'teams', 1], msg: "String should match pattern '^[A-Z][A-Z0-9]{0,6}$'" },
		{ loc: ['sources', 10, 'teams', 2], msg: "String should match pattern '^[A-Z][A-Z0-9]{0,6}$'" }
	];
	let srcLinearPublic = $state<SourceConfig>({ type: 'linear', workspace: 'acme', teams: [] });
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
	const mapTerritory = new Map(syntheticGraph.nodes.map((n) => [n.uid, n.territory]));
	const drawnUid = (uid: string) => mapTerritory.get(uid) ?? null;
	const runningTrail = trailOf(runningRun, drawnUid);
	const doneTrail = trailOf(doneRun, drawnUid);
	const failedTrail = trailOf(failedRun, drawnUid);
	const keeperTrail = trailOf(keeper.keeperRun, drawnUid);
	const archivistTrail = trailOf(archivistRun, drawnUid);
	// The approval card's live sample: any name approves after a short wait.
	let approverName = $state('');
	let approverError = $state<string | null>(null);
	const approveLater = () => new Promise<null>((done) => setTimeout(() => done(null), 900));
	const neverDecides = () => new Promise<null>(() => {});
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

<svelte:window onresize={measureSplit} />

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

	<Card title="References">
		<div class="stack">
			<p>
				Text with a <RefLink href="https://github.com/acme/app/pull/12">#12</RefLink> in it, a path
				<RefLink href="https://github.com/acme/app/blob/HEAD/src/auth/token.py#L42" code>src/auth/token.py:42</RefLink>
				and an icon link beside a row's name:
				<RefLink icon href="https://github.com/acme/app/commit/a001" label="commit a001" />
			</p>
			<p>
				<RefText
					runs={textRuns('Bodies link #12, acme/web#3 and src/auth/token.py:42 but not page#3, &#12; or https://example.com/a.py.', refRepo)}
				/>
			</p>
			<WalkAnswer answer={refAnswer} refs={refAnswerRefs} />
			<p class="note">
				Answer refs: #1 and #10 open the url the walk saw (example.com here); #23 and the paths open in
				the company's one GitHub repo; <code>identity</code> is a word, so it stays code.
			</p>
		</div>
	</Card>

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
			path. Linear: the workspace and its team keys; an error banner while the data permission is
			Public, and the API's pattern errors as sentences under their field.
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
			<SourceCard bind:source={srcLinear} index={8} dataPermission="synthetic" errors={[]} onremove={noop} checks={checksFound} />
			<SourceCard bind:source={srcLinearEmpty} index={9} dataPermission="own" errors={[{ loc: ['sources', 9, 'workspace'], msg: "String should match pattern '^[a-z0-9-]+$'" }]} onremove={noop} checks={checksFound} />
			<SourceCard bind:source={srcLinearBad} index={10} dataPermission="own" errors={linearBadErrors} onremove={noop} checks={checksFound} />
			<SourceCard bind:source={srcLinearPublic} index={11} dataPermission="public" errors={[]} onremove={noop} checks={checksFound} />
		</div>
	</Card>

	<Card title="Source row" id="source-row">
		<p class="note">
			One source on the Sources page (direction A, the source ledger), a <code>tbody</code> inside
			the page's table: synced and open (GitHub), two folders sharing one count (the first one's
			window changed, and it takes a record's own <code>slack_export</code> label), skipped (folder
			missing), blocked (no key, so every sync fails), never synced with a long name, and one
			syncing while another is busy.
		</p>
		<div class="ledger-sample">
			<table>
				<thead>
					<tr>
						<th scope="col">Source</th>
						<th scope="col">Status</th>
						<th scope="col">Last sync</th>
						<th scope="col">Read up to</th>
						<th scope="col">In the graph</th>
						<th scope="col"><span class="sr-only">Actions</span></th>
					</tr>
				</thead>
				{#each sourceSamples.sampleSources as source, i (source.key)}
					<SourceRow
						{source}
						credit={sourceSamples.sampleLedger.credits.get(source.key)!}
						since="2026-04-15"
						open={i < 2}
						settingsHref="#source-row"
						onsync={noop}
						syncing={i === 0}
						busy={i === 5}
						locations={sourceSamples.sampleLocations}
					/>
				{/each}
			</table>
		</div>
	</Card>

	<Card title="Company form">
		<p class="note">
			The fields of a company file. One step at a time, in the add-company wizard (company,
			sources, rules) and in the Settings tabs. For an existing company (Settings) the graph name
			is not a field, the data permission is a row of radios and Name to login starts empty.
			Errors show under their field; the form never calls the API. The last form holds duplicate
			tags, as a hand-edited file can.
		</p>
		<div class="forms">
			<figure>
				<CompanyForm bind:draft={formNew} section="company" errors={[]} />
				<figcaption>Company step, empty</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formNew} section="sources" errors={[]} />
				<figcaption>Sources step, Public data: Linear is off, with the reason</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formErrors} section="company" errors={formErrorList} />
				<figcaption>Company step, with errors</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formLocked} section="company" errors={[]} existing />
				<figcaption>Company tab in Settings (an existing company)</figcaption>
			</figure>
			<figure>
				<CompanyForm bind:draft={formAll} section="rules" errors={[]} existing />
				<figcaption>Systems and people tab in Settings, no names yet</figcaption>
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
				{ value: 'path', label: 'Graph path', dirty: true },
				{ value: 'empty', label: 'Empty state', count: 3, errors: 2 }
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
				<WalkAnswer answer={walks.withMcp} />
				<figcaption>Answer citing an MCP result next to a graph node</figcaption>
			</figure>
			<figure>
				<WalkAnswer answer={keeper.withClaim} />
				<figcaption>Answer citing a Keeper claim (the Keeper mark) next to a source</figcaption>
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

	<Card title="Walk ledger (Ask)">
		<p class="note">
			One row per graph step in plain words, a mark for how it ended, rows and time. Once the answer
			is in, repeated calls of one tool fold into one row; a call that found nothing or failed keeps
			its own row and says so. The last row is the answer check.
		</p>
		<div class="walks">
			<figure>
				<WalkLedger steps={walks.running} />
				<figcaption>Running: step 1 done, step 2 reading rows</figcaption>
			</figure>
			<figure>
				<WalkLedger steps={walks.mixed} settled />
				<figcaption>Settled: three calls folded into one row, one empty call, one failed call, the check</figcaption>
			</figure>
			<figure>
				<WalkLedger
					steps={walks.done}
					settled
					open={ledgerOpen}
					ontoggle={(key) => (ledgerOpen = ledgerOpen === key ? null : key)}
					cites={walkCites}
					active={walkActive}
				/>
				<figcaption>A row open: its call and rows; rows a citation used carry its number (click a row)</figcaption>
			</figure>
			<figure>
				<WalkLedger steps={walks.rough} settled />
				<figcaption>The answer check sent back with a reason</figcaption>
			</figure>
			<figure>
				<WalkLedger steps={walks.archivistRunning} />
				<figcaption>Nested steps, live: the Archivist's search is done, its read is running</figcaption>
			</figure>
			<figure>
				<WalkLedger steps={walks.archivistDone} settled />
				<figcaption>Nested steps, done: the row says what the Archivist reported</figcaption>
			</figure>
			<figure>
				<WalkAnswer answer={walks.archived} />
				<figcaption>Answer citing an archived source (Archive · year badge)</figcaption>
			</figure>
			<figure>
				<StepRows step={walks.done[2]} cites={walkCites} active={walkActive} />
				<figcaption>Step rows: paths read as chains of nodes and relationships</figcaption>
			</figure>
			<figure>
				<StepRows step={walks.mixed[3]} />
				<figcaption>Step rows: a call that found nothing</figcaption>
			</figure>
		</div>
	</Card>

	<Card title="Graph walk with earlier context (Ask)">
		<p class="note">
			A follow-up starts from what the conversation already knows. Nodes and links the earlier
			questions found that touch this answer are drawn dashed and faint until a step reaches them.
			New links draw on from their ends, and nodes glide with their links when a step lands.
		</p>
		<div class="walks">
			<figure>
				<GraphWalk steps={walks.followUp} />
				<figcaption>Q2 without context</figcaption>
			</figure>
			<figure>
				<GraphWalk steps={walks.followUp} {carried} />
				<figcaption>Q2 with Q1 as context: {carried.nodes.length} earlier nodes, dashed</figcaption>
			</figure>
		</div>
	</Card>

	<Card title="Splitter">
		<p class="note">
			Drag the line, or focus it and use the arrow keys (Shift for bigger steps), Home and End. Enter
			folds the pane and opens it again; a double-click puts it back to 38%. Drag past the narrowest
			width and the pane folds.
		</p>
		<div class="split-box" bind:this={splitBox} bind:clientWidth={splitWidth}>
			<div class="split-pane">
				<p>Conversation</p>
				<p class="muted">Takes the rest</p>
			</div>
			<div class="split-pane right" style:width={splitPane}>
				<p>Walk</p>
				<p class="muted tabular">{splitFolded ? 'Folded' : `${Math.round(splitSize * 100)}%`}</p>
			</div>
			{#if splitWidth}
				<div class="split-line" style:right={splitPane}>
					<Splitter
						bind:size={splitSize}
						bind:folded={splitFolded}
						container={splitWidth}
						right={splitRight}
						label="Resize the walk box"
					/>
				</div>
			{/if}
		</div>
	</Card>

	<Card title="Ask lane">
		<p class="note">
			One question and everything it led to: the strip across the top, the conversation on the left
			and that question's own walk on the right. The walk draws when the lane is near the screen.
		</p>
		<div class="lanes">
			<figure>
				<div class="lane-frame">
					<AskLane turn={walks.laneRunning} index={0} brain="Synthetic Co" walkWidth="26rem" />
				</div>
				<figcaption>Running: the ledger shows step 2 reading rows; no answer yet</figcaption>
			</figure>
			<figure>
				<div class="lane-frame">
					<AskLane turn={walks.laneDone} index={0} brain="Synthetic Co" walkWidth="26rem" />
				</div>
				<figcaption>Done: answer with citations, thumbs and Replay walk</figcaption>
			</figure>
			<figure>
				<div class="lane-frame">
					<AskLane turn={walks.laneFollowUp} index={1} earlier={walks.done} brain="Synthetic Co" walkWidth="26rem" />
				</div>
				<figcaption>A follow-up (Q2) running, with Q1 as dashed context in its walk</figcaption>
			</figure>
			<figure>
				<div class="lane-frame">
					<AskLane turn={walks.laneDone} index={0} brain="Synthetic Co" walkWidth="var(--walk-strip)" folded />
				</div>
				<figcaption>The walk column folded to its strip: a dot and the node count</figcaption>
			</figure>
		</div>
	</Card>

	<Card title="Chat list and answer timeline (Ask)">
		<div class="walks">
			<figure>
				<ChatList
					threads={chatSamples.chats}
					current="c2"
					hrefOf={(id) => `?chat=${id}`}
					more
					now={chatSamples.NOW}
					ondelete={() => {}}
				/>
				<figcaption>Answering, open, stopped, failed and older chats; more to read</figcaption>
			</figure>
			<figure>
				<ChatList threads={[]} hrefOf={(id) => `?chat=${id}`} />
				<ChatList threads={[]} hrefOf={(id) => `?chat=${id}`} loading />
				<ChatList threads={chatSamples.chats.slice(1, 2)} hrefOf={(id) => `?chat=${id}`} error="FalkorDB is not reachable" now={chatSamples.NOW} />
				<figcaption>No chats yet; loading; a failed read</figcaption>
			</figure>
			<figure>
				<TurnTimeline calls={chatSamples.timeline} steps={chatSamples.timelineSteps} running />
				<figcaption>Timeline open: reasoning, text, graph tools, an MCP call with its result, the answer check</figcaption>
			</figure>
			<figure>
				<TurnTimeline calls={chatSamples.timeline.slice(0, 1)} steps={walks.running} />
				<figcaption>Folded; open it to see a graph call still running</figcaption>
			</figure>
		</div>
	</Card>

	<Card title="Model picker (Ask)">
		<div class="walks">
			<figure>
				<ModelPicker
					models={chatSamples.models}
					selected={liveModel}
					defaultId="claude-sonnet-5-5"
					onpick={(id) => (liveModel = id)}
				/>
				<figcaption>Live: open it, pick a model; Sonnet 5.5 is the default, Fable 5.1 is slow</figcaption>
			</figure>
			<figure>
				<ModelPicker models={chatSamples.models} selected="claude-opus-5-5" defaultId="claude-sonnet-5-5" disabled onpick={() => {}} />
				<figcaption>Locked while an answer runs</figcaption>
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
			<h3 class="sub">Loading the model, embedding text, and embeddings off</h3>
			<BuildProgress snapshot={builds.embedLoading} />
			<BuildProgress snapshot={builds.embedding} />
			<BuildProgress snapshot={builds.embedSkipped} />
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

	<Card title="Agent trail">
		<p class="note">
			The Systems page: an agent's run drawn over the territory map. Each step sits on the node it
			was about, numbered, joined by an ink line; nodes it touched stay bright. While the run is
			going, an ink ring and a label mark where the agent is now, and its territory is outlined.
		</p>
		<div class="map-sample">
			<TerritoryMap
				view={syntheticGraph}
				layout={mapLayout}
				trail={runningTrail}
				here="Ask agent · {doingNow(runningRun)}"
				scrollZoom={false}
			/>
		</div>
		<h3 class="sub">Run finished</h3>
		<div class="map-sample short">
			<TerritoryMap view={syntheticGraph} layout={mapLayout} trail={doneTrail} scrollZoom={false} />
		</div>
	</Card>

	<Card title="Agent run" id="agent-run">
		<p class="note">
			The Systems page's rail: one run's steps, numbered as on the map. A ring is the step
			running now; a dash is a step with nothing on the map.
		</p>
		<div class="runs">
			<div>
				<h3 class="sub">Working now</h3>
				<AgentRun run={runningRun} trail={runningTrail} href="#agent-run" urlOf={(uid) => syntheticGraph.nodes.find((n) => n.uid === uid)?.url ?? null} />
			</div>
			<div>
				<h3 class="sub">Done</h3>
				<AgentRun run={doneRun} trail={doneTrail} href="#agent-run" />
			</div>
			<div>
				<h3 class="sub">Failed, no steps</h3>
				<AgentRun run={failedRun} trail={failedTrail} />
			</div>
			<div>
				<h3 class="sub">Archivist run</h3>
				<AgentRun run={archivistRun} trail={archivistTrail} />
			</div>
			<div>
				<h3 class="sub">Keeper review, working now</h3>
				<AgentRun run={keeper.keeperRun} trail={keeperTrail} />
			</div>
		</div>
		<h3 class="sub">Keeper review on the map: {hereLabel(keeper.keeperRun)}</h3>
		<div class="map-sample short">
			<TerritoryMap
				view={syntheticGraph}
				layout={mapLayout}
				trail={keeperTrail}
				here={hereLabel(keeper.keeperRun)}
				scrollZoom={false}
			/>
		</div>
	</Card>

	<Card title="Claim approval" id="claim-approval">
		<p class="note">
			A Keeper claim waiting for a lead, as the review page's detail pane shows it: its kind and
			subject, the statement, why it needs a lead (one row per reason), the gap it answers, its
			evidence, then an optional reason with Reject and Approve. The name is typed once in the
			page's header; with none, the page says so under that field. Type a name and press Approve.
		</p>
		<div class="claim-name">
			<Input label="Deciding as" placeholder="Your name" bind:value={approverName} error={approverError ?? undefined} oninput={() => (approverError = null)} />
		</div>
		<div class="claims">
			<div>
				<h3 class="sub">Waiting (try it)</h3>
				<div class="claim-box">
					<ClaimApproval
						claim={keeper.pendingClaim}
						gapText={keeper.gapTexts.get('gap:refunds')}
						evidence={keeper.pendingEvidence}
						name={approverName}
						onnameerror={(m) => (approverError = m)}
						ondecide={approveLater}
					>
						{#snippet work()}<KeeperTrail trail={keeper.pendingTrail} refsOf={galleryRefs} />{/snippet}
					</ClaimApproval>
				</div>
			</div>
			<div>
				<h3 class="sub">Sending the approval</h3>
				<div class="claim-box"><ClaimApproval claim={keeper.pendingClaim} evidence={keeper.pendingEvidence} name="Dana Lee" busy="approve" ondecide={neverDecides} /></div>
			</div>
			<div>
				<h3 class="sub">Someone decided first (409)</h3>
				<div class="claim-box">
					<ClaimApproval
						claim={keeper.pendingClaim}
						evidence={keeper.pendingEvidence}
						name="Dana Lee"
						failure={{ message: 'Someone already decided this claim. The list now shows where it stands.', gone: true }}
						ondecide={approveLater}
					/>
				</div>
			</div>
			<div>
				<h3 class="sub">Brain unavailable (503)</h3>
				<div class="claim-box">
					<ClaimApproval
						claim={keeper.pendingClaim}
						evidence={keeper.pendingEvidence}
						name="Dana Lee"
						failure={{ message: 'The brain of synthetic is not there (brain_synthetic is missing). Build the company, then approve again.' }}
						ondecide={approveLater}
					/>
				</div>
			</div>
			<div>
				<h3 class="sub">Reason refused (422)</h3>
				<div class="claim-box">
					<ClaimApproval
						claim={keeper.pendingClaim}
						evidence={keeper.pendingEvidence}
						name="Dana Lee"
						failure={{ field: 'why', message: 'Keep the reason to 500 characters.' }}
						ondecide={approveLater}
					/>
				</div>
			</div>
			<div>
				<h3 class="sub">Every reason, no evidence, long text</h3>
				<div class="claim-box"><ClaimApproval claim={keeper.longClaim} gapText="Why do invoice emails go out from a queue now and not from checkout?" evidence={[]} name="Dana Lee" ondecide={approveLater} /></div>
			</div>
		</div>
	</Card>

	<Card title="Keeper trail">
		<p class="note">
			How the Keeper got to a claim, inside the claim's detail: the review that wrote it, then pm,
			qa and the Keeper in the order they worked, each with what it drafted, what it cited and its
			graph reads (open them). A claim from a person's reply in Ask has no review, so the gap's log
			stands in.
		</p>
		<div class="runs">
			<div>
				<h3 class="sub">A review's jobs</h3>
				<KeeperTrail trail={keeper.pendingTrail} refsOf={galleryRefs} />
			</div>
			<div>
				<h3 class="sub">From Ask (log only)</h3>
				<KeeperTrail trail={keeper.interviewTrail} refsOf={galleryRefs} />
			</div>
			<div>
				<h3 class="sub">Loading</h3>
				<KeeperTrail trail={null} refsOf={galleryRefs} />
			</div>
			<div>
				<h3 class="sub">Can't read it</h3>
				<KeeperTrail trail={null} failed="The API did not answer." refsOf={galleryRefs} />
			</div>
		</div>
	</Card>

	<Card title="Keeper log">
		<p class="note">
			The Keeper's log in the Systems page's rail, newest first: who did what, in words, then why. An
			auto-accept reads as the Keeper. A line about a waiting claim links to its card.
		</p>
		<div class="runs">
			<div>
				<h3 class="sub">A review and a decision</h3>
				<KeeperLog
					entries={keeper.logEntries}
					gapText={(uid) => keeper.gapTexts.get(uid) ?? null}
					claimHref={(uid) => (uid === keeper.pendingClaim.uid ? '#claim-approval' : null)}
				/>
			</div>
			<div>
				<h3 class="sub">Empty</h3>
				<KeeperLog entries={[]} />
			</div>
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
	.claim-name {
		max-width: 16rem;
		margin-bottom: var(--space-4);
	}
	.claims {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 34rem), 1fr));
		gap: var(--space-6);
	}
	.claim-box {
		height: 34rem;
		overflow: hidden;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.runs {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
		gap: var(--space-6);
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
	.ledger-sample {
		overflow-x: auto;
		margin-top: var(--space-4);
		background: var(--color-surface);
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
	}
	.ledger-sample table {
		width: 100%;
		min-width: 56rem;
		border-collapse: collapse;
	}
	.ledger-sample thead th {
		padding: var(--space-2) var(--space-4);
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		color: var(--color-text-muted);
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
	.split-box {
		position: relative;
		display: flex;
		height: 12rem;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.split-pane {
		flex: 1;
		min-width: 0;
		padding: var(--space-4);
	}
	.split-pane.right {
		flex: none;
		margin-left: var(--splitter-hit);
		background: var(--color-surface-sunken);
	}
	.split-pane p {
		margin: 0;
	}
	.split-pane .muted {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.split-line {
		position: absolute;
		top: 0;
		bottom: 0;
	}
	.lanes {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.lanes figure {
		margin: 0;
	}
	.lanes figcaption {
		margin-top: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.lane-frame {
		overflow-x: auto;
		border: var(--border-hair) solid var(--color-line);
		border-radius: var(--radius-md);
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
