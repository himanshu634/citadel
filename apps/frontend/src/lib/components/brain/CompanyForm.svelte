<!--
@component
The fields of a company file, for one wizard step (`section` company, sources or rules) or all
three at once (`all`, for Settings). It edits `draft` in place and never calls the API: the page
validates and passes the result back as `errors`. An error shows under the field whose path its
`loc` starts with (`['sources', 0, 'repo']` is the repo input of source card 0); the ones no field
shows are listed at the foot of their section, so nothing blocks the user without a reason.

The graph name follows the company name until someone edits it (derived from the two values, so it
survives leaving and coming back to the step). `slugLocked` shows it read-only, for a company that
exists. Fixed rows of the "Name to login" table are local state seeded from the draft once;
Settings should mount a new form when it loads another company.
-->
<script lang="ts">
	import { Plus, Trash2 } from '@lucide/svelte';
	import Button from '../ui/Button.svelte';
	import ChoiceCard from '../ui/ChoiceCard.svelte';
	import Input from '../ui/Input.svelte';
	import Select from '../ui/Select.svelte';
	import TagInput from '../ui/TagInput.svelte';
	import SourceCard from './SourceCard.svelte';
	import { slugify } from '$lib/companies';
	import {
		SECTIONS,
		SOURCE_KINDS,
		addSourceBlocked,
		aliasRowsToRecord,
		blankSource,
		errorsIn,
		friendly,
		messageAt,
		recordToAliasRows,
		unmatched,
		visibleErrors,
		type AliasRow,
		type Loc,
		type Section
	} from '$lib/onboarding';
	import type { CompanyConfig, DataPermission, FieldError } from '$lib/types';

	type Props = {
		draft: CompanyConfig;
		section: Section | 'all';
		errors: FieldError[];
		slugLocked?: boolean;
	};

	let { draft = $bindable(), section, errors, slugLocked = false }: Props = $props();

	// The file always has these two blocks; give the form something to edit when a draft lacks them.
	if (!draft.systems) draft.systems = { rules: [], fallback: 'depth_2', ignore: [] };
	if (!draft.people) draft.people = { bots: [], aliases: {} };
	if (!draft.systems.rules) draft.systems.rules = [];
	if (!draft.systems.ignore) draft.systems.ignore = [];
	if (!draft.people.bots) draft.people.bots = [];

	type Fallback = NonNullable<NonNullable<CompanyConfig['systems']>['fallback']>;
	// Set just above, so these exist; the template reads them through these names.
	const systems = $derived(draft.systems!);
	const people = $derived(draft.people!);

	const shown = $derived<Section[]>(section === 'all' ? SECTIONS : [section]);
	const mine = (s: Section) => errorsIn(errors, s);

	// --- Company ---------------------------------------------------------------------------------
	function setName(value: string) {
		// Follow only while the graph name is still what the name would give.
		const following = !slugLocked && draft.slug === slugify(draft.name);
		draft.name = value;
		if (following) draft.slug = slugify(value);
	}

	// A graph name nobody has typed yet is not an error to show (the page's gates agree).
	const slugErrors = $derived(visibleErrors(draft, errors));

	const PERMISSIONS: { value: DataPermission; title: string; description: string }[] = [
		{ value: 'public', title: 'Public', description: 'Open-source repositories anyone can read.' },
		{ value: 'own', title: 'Own', description: "Your company's data. You confirm you may ingest it." },
		{ value: 'synthetic', title: 'Synthetic', description: 'Generated demo data for trying Citadel.' }
	];

	// --- Sources ---------------------------------------------------------------------------------
	function addSource(type: string) {
		draft.sources.push(blankSource(type));
	}
	function removeSource(index: number) {
		draft.sources.splice(index, 1);
	}
	// A kind the data permission rules out stays in the row, off, with its reason beside it.
	const uid = $props.id();
	const addKinds = $derived(
		SOURCE_KINDS.map((kind) => ({ ...kind, blocked: addSourceBlocked(kind.type, draft.data_permission) }))
	);

	// --- Systems and people ----------------------------------------------------------------------
	const FALLBACKS = [
		{ value: 'depth_1', label: 'Top folder, like src' },
		{ value: 'depth_2', label: 'Two folders deep, like src/serializers' },
		{ value: 'depth_3', label: 'Three folders deep' },
		{ value: 'none', label: 'No system' }
	];

	let aliasRows = $state<AliasRow[]>(recordToAliasRows(draft.people?.aliases ?? {}));
	if (aliasRows.length === 0) aliasRows.push({ name: '', login: '' });
	function syncAliases() {
		if (draft.people) draft.people.aliases = aliasRowsToRecord(aliasRows);
	}
	function addAliasRow() {
		aliasRows.push({ name: '', login: '' });
	}

	// --- Errors no field shows, per section -------------------------------------------------------
	const rendered = $derived<Record<Section, Loc[]>>({
		company: [['slug'], ['name'], ['window', 'since']],
		sources: draft.sources.map((_, i) => ['sources', i]),
		rules: [
			...(draft.systems?.rules ?? []).flatMap((_, i): Loc[] => [
				['systems', 'rules', i, 'match'],
				['systems', 'rules', i, 'system']
			]),
			['systems', 'fallback'],
			['systems', 'ignore'],
			['people', 'bots'],
			...aliasRows.map((row): Loc => ['people', 'aliases', row.name])
		]
	});
	const loose = (s: Section) => unmatched(mine(s), rendered[s]);
</script>

{#snippet looseErrors(s: Section)}
	{@const list = loose(s)}
	{#if list.length > 0}
		<ul class="loose" role="alert">
			{#each list as e, i (i)}
				<li>{friendly(e)} <code>{e.loc.join('.')}</code></li>
			{/each}
		</ul>
	{/if}
{/snippet}

<div class="form">
	{#if shown.includes('company')}
		<section class="group" aria-labelledby="h-company">
			<div>
				<h2 id="h-company" tabindex="-1">Company</h2>
				<p class="lead">Name the company and say what data you are allowed to read.</p>
			</div>
			<div class="two">
				<Input
					label="Company name"
					autocomplete="off"
					bind:value={() => draft.name, setName}
					hint="Shown in the rail and on every page."
					error={messageAt(errors, ['name'])}
				/>
				<Input
					label="Graph name"
					prefix="brain_"
					autocomplete="off"
					spellcheck="false"
					readonly={slugLocked}
					bind:value={draft.slug}
					hint={slugLocked
						? 'A company keeps its graph name.'
						: 'Lowercase letters, digits and underscores, starting with a letter or digit. It cannot change after the first build.'}
					error={messageAt(slugErrors, ['slug'])}
				/>
			</div>
			<fieldset class="choices">
				<legend>Data permission</legend>
				<div class="cards">
					{#each PERMISSIONS as p (p.value)}
						<ChoiceCard
							name="data_permission"
							value={p.value}
							title={p.title}
							description={p.description}
							bind:group={draft.data_permission}
						/>
					{/each}
				</div>
				{#if messageAt(errors, ['data_permission'])}
					<p class="error">{messageAt(errors, ['data_permission'])}</p>
				{/if}
			</fieldset>
			<div class="narrow">
				<Input
					label="Read activity since"
					type="date"
					bind:value={draft.window.since}
					hint="Older activity is skipped. Changing this later rebuilds the graph."
					error={messageAt(errors, ['window', 'since'])}
				/>
			</div>
			{@render looseErrors('company')}
		</section>
	{/if}

	{#if shown.includes('sources')}
		<section class="group" aria-labelledby="h-sources">
			<div>
				<h2 id="h-sources" tabindex="-1">Sources</h2>
				<p class="lead">
					Where {draft.name.trim() || 'the company'}'s engineering work lives. Each source is
					downloaded once into a cache, so rebuilding the graph costs no API calls.
				</p>
			</div>
			{#each draft.sources as source, i (source)}
				<SourceCard
					bind:source={draft.sources[i]}
					index={i}
					dataPermission={draft.data_permission}
					errors={mine('sources')}
					onremove={() => removeSource(i)}
				/>
			{:else}
				<p class="none">No sources yet. Add at least one below.</p>
			{/each}
			<div class="add">
				<span class="label" id="add-source">Add a source</span>
				<div class="buttons" role="group" aria-labelledby="add-source">
					{#each addKinds as kind (kind.type)}
						<Button
							size="sm"
							disabled={kind.blocked !== null}
							aria-describedby={kind.blocked ? `${uid}-${kind.type}-why` : undefined}
							onclick={() => addSource(kind.type)}
						>
							<Plus aria-hidden="true" />{kind.title}
						</Button>
					{/each}
				</div>
				{#each addKinds as kind (kind.type)}
					{#if kind.blocked}
						<p class="hint why" id="{uid}-{kind.type}-why">{kind.blocked}</p>
					{/if}
				{/each}
			</div>
			{@render looseErrors('sources')}
		</section>
	{/if}

	{#if shown.includes('rules')}
		<section class="group" aria-labelledby="h-rules">
			<div>
				<h2 id="h-rules" tabindex="-1">Systems and people</h2>
				<p class="lead">
					Citadel groups changed files into systems and leaves bots out of the people list. The
					defaults work; refine them now or later in the company's settings.
				</p>
			</div>

			<fieldset class="rules">
				<legend>Path rules</legend>
				<p class="hint">
					The first matching rule wins. Patterns are globs on the path inside the repository.
				</p>
				{#if (draft.systems?.rules ?? []).length > 0}
					<table>
						<thead>
							<tr>
								<th scope="col">Path pattern</th>
								<th scope="col">System</th>
								<th scope="col" class="x"><span class="sr-only">Remove</span></th>
							</tr>
						</thead>
						<tbody>
							{#each draft.systems?.rules ?? [] as rule, i (rule)}
								<tr>
									<td>
										<Input
											label="Pattern {i + 1}"
											hideLabel
											mono
											placeholder="services/auth/**"
											spellcheck="false"
											bind:value={rule.match}
											error={messageAt(errors, ['systems', 'rules', i, 'match'])}
										/>
									</td>
									<td>
										<Input
											label="System {i + 1}"
											hideLabel
											placeholder="Auth"
											bind:value={rule.system}
											error={messageAt(errors, ['systems', 'rules', i, 'system'])}
										/>
									</td>
									<td class="x">
										<Button
											variant="ghost"
											size="sm"
											iconOnly
											label="Remove rule {i + 1}"
											onclick={() => draft.systems?.rules?.splice(i, 1)}
										>
											<Trash2 aria-hidden="true" />
										</Button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
				<div>
					<Button size="sm" onclick={() => draft.systems?.rules?.push({ match: '', system: '' })}>
						<Plus aria-hidden="true" />Add rule
					</Button>
				</div>
			</fieldset>

			<div class="two">
				{#if draft.systems}
					<Select
						label="Files no rule matches"
						options={FALLBACKS}
						bind:value={() => draft.systems?.fallback ?? 'depth_2', (v) => (systems.fallback = v as Fallback)}
						error={messageAt(errors, ['systems', 'fallback'])}
					/>
					<TagInput
						label="Ignore paths"
						mono
						placeholder="vendor/**"
						bind:values={() => systems.ignore ?? [], (v) => (systems.ignore = v)}
						hint="Files matching these globs are left out. Press Enter to add one."
						error={messageAt(errors, ['systems', 'ignore'])}
					/>
				{/if}
			</div>

			<div class="two">
				{#if draft.people}
					<TagInput
						label="Bots"
						mono
						placeholder="dependabot[bot]"
						bind:values={() => people.bots ?? [], (v) => (people.bots = v)}
						hint="Their activity stays in the graph but they are not counted as people."
						error={messageAt(errors, ['people', 'bots'])}
					/>
				{/if}
				<fieldset class="rules">
					<legend>Name to login</legend>
					<table>
						<thead>
							<tr>
								<th scope="col">Git author name</th>
								<th scope="col">GitHub login</th>
							</tr>
						</thead>
						<tbody>
							{#each aliasRows as row, i (row)}
								<tr>
									<td>
										<Input
											label="Author name {i + 1}"
											hideLabel
											placeholder="Sam O."
											bind:value={row.name}
											oninput={syncAliases}
											error={row.name ? messageAt(errors, ['people', 'aliases', row.name]) : undefined}
										/>
									</td>
									<td>
										<Input
											label="Login {i + 1}"
											hideLabel
											mono
											placeholder="sokafor"
											spellcheck="false"
											bind:value={row.login}
											oninput={syncAliases}
										/>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
					<p class="hint">For people whose commits use a different name than their login.</p>
					<div>
						<Button size="sm" onclick={addAliasRow}><Plus aria-hidden="true" />Add row</Button>
					</div>
				</fieldset>
			</div>
			{@render looseErrors('rules')}
		</section>
	{/if}
</div>

<style>
	.form,
	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		min-width: 0;
	}
	h2 {
		font-size: var(--text-xl);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-heading);
	}
	h2:focus {
		outline: none;
	}
	.lead {
		margin-top: var(--space-1);
		max-width: 60ch;
		color: var(--color-text-muted);
	}
	.two {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-5);
		align-items: start;
	}
	.narrow {
		max-width: 20rem;
	}
	fieldset {
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	legend,
	.label {
		padding: 0;
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.cards {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: var(--space-3);
	}
	.why {
		margin-top: var(--space-2);
	}
	.hint,
	.none {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.rules {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	table {
		width: 100%;
		table-layout: fixed;
		border-collapse: collapse;
	}
	th {
		padding: 0 var(--space-2) var(--space-1) 0;
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		color: var(--color-text-muted);
	}
	td {
		padding: 0 var(--space-2) var(--space-2) 0;
		vertical-align: top;
	}
	th.x,
	td.x {
		width: 2.5rem;
		padding-right: 0;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.buttons :global(.btn svg) {
		width: 1rem;
		height: 1rem;
	}
	.rules :global(.btn svg) {
		width: 1rem;
		height: 1rem;
	}
	.error,
	.loose {
		font-size: var(--text-xs);
		color: var(--color-danger);
	}
	.loose {
		margin: 0;
		padding-left: var(--space-4);
	}
	code {
		font-family: var(--font-mono);
	}
	@media (max-width: 52rem) {
		.two,
		.cards {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
