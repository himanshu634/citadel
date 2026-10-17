/** Shapes the UI renders. They mirror the brain's graph labels (apps/brain/brain/canonical.py). */

export type NodeType = 'person' | 'team' | 'system' | 'work-item' | 'change' | 'document';

export const NODE_LABELS: Record<NodeType, string> = {
	person: 'Person',
	team: 'Team',
	system: 'System',
	'work-item': 'Work item',
	change: 'Change',
	document: 'Document'
};

export const NODE_PLURALS: Record<NodeType, string> = {
	person: 'People',
	team: 'Teams',
	system: 'Systems',
	'work-item': 'Work items',
	change: 'Changes',
	document: 'Documents'
};

export type WorkItemKind = 'pull_request' | 'issue' | 'ticket' | 'thread';

export interface GraphNodeRef {
	uid: string;
	type: NodeType;
	label: string;
}

export interface PathStep {
	node: GraphNodeRef;
	/** Relationship to the next step, e.g. AUTHORED. Omitted on the last step. */
	edge?: string;
}

export interface Source {
	uid: string;
	title: string;
	meta: string;
	url?: string;
}

export interface CitedAnswer {
	question: string;
	/** Answer text split into runs; a run with `cite` renders citation chips after it. */
	parts: { text: string; cite?: number[] }[];
	path: PathStep[];
	sources: Source[];
}

export interface WorkItem {
	uid: string;
	kind: WorkItemKind;
	number?: number;
	title: string;
	/** Source-specific (open, closed, merged, done ...); the row styles `open` and `merged`. */
	state: string;
	author?: string;
	/** An ISO date or timestamp; omitted when the source gave none. */
	date?: string;
	/** The systems it touched, comma-separated. */
	system?: string;
}

export interface MenuItem {
	value: string;
	label: string;
	hint?: string;
	selected?: boolean;
}

// --- Companies and builds (the HTTP API) --------------------------------------------------------
// Written by hand to match apps/backend/backend/api/models.py, jobs.py, config_diff.py,
// apps/brain/brain/events.py and the row models in apps/brain/brain/tools.py. Field names are the
// backend's (snake_case), not renamed.

/** `unknown`: FalkorDB did not answer and no build says otherwise (`graph_reachable` is false). */
export type CompanyStatus = 'ready' | 'building' | 'failed' | 'empty' | 'invalid' | 'unknown';
export type DataPermission = 'public' | 'synthetic' | 'own';

export type BuildKind = 'build' | 'rebuild';
export type BuildState = 'queued' | 'running' | 'done' | 'failed' | 'stopped';
export type BuildStage = 'reset' | 'prepare' | 'fetch' | 'records' | 'normalize' | 'load' | 'done';
export type BuildStatus = 'waiting' | 'running' | 'done' | 'skipped' | 'failed' | 'stopped';

export interface BuildEvent {
	slug: string;
	stage: BuildStage;
	status: BuildStatus;
	/** Adapter key such as `github:FalkorDB/FalkorDB`; null for a stage of the whole company. */
	source: string | null;
	count: number | null;
	message: string | null;
	at: string;
	/** Final event only: what the load wrote and dropped. */
	totals: Record<string, unknown> | null;
	/** The build's step when this happened (see `BuildSummary.step`); absent in old build files. */
	step?: number | null;
}

/** The short form of a build that a company list entry carries (the last build, in any state). */
export interface BuildSummary {
	kind: BuildKind;
	state: BuildState;
	stage: BuildStage | null;
	/** The planned stage order; the ingest stages run once per source. */
	stages: BuildStage[];
	started_at: string;
	/**
	 * "Step n of N", counted by the backend with every source's stages: `step` only goes forward
	 * and keeps its value when the build ends. Null while queued, and both null (or absent) for
	 * an old build file or a company whose sources could not be read.
	 */
	step?: number | null;
	steps?: number | null;
}

export interface BuildSnapshot {
	slug: string;
	kind: BuildKind;
	state: BuildState;
	started_at: string;
	stages: BuildStage[];
	ended_at: string | null;
	events: BuildEvent[];
	error: string | null;
	/** As in `BuildSummary`. */
	step?: number | null;
	steps?: number | null;
}

export interface Company {
	slug: string;
	name: string;
	/** null when the company's YAML is invalid. */
	data_permission: DataPermission | null;
	/** Decide "building" from this, not from `build` (which may be a finished build). */
	status: CompanyStatus;
	last_synced_at: string | null;
	/** The YAML's problem (`invalid`) or the last build's (`failed`). */
	error: string | null;
	build: BuildSummary | null;
	graph_reachable: boolean;
}

/** A source entry of the company YAML; `type` selects the adapter, the rest is its own fields. */
export interface SourceConfig {
	type: string;
	[field: string]: unknown;
}

/** The company YAML as the API reads and writes it (apps/brain/brain/config.py CompanyConfig). */
export interface CompanyConfig {
	slug: string;
	name: string;
	data_permission: DataPermission;
	window: { since: string };
	sources: SourceConfig[];
	systems?: {
		rules?: { match: string; system: string }[];
		fallback?: 'depth_1' | 'depth_2' | 'depth_3' | 'none';
		ignore?: string[];
	};
	people?: { bots?: string[]; aliases?: Record<string, string> };
	/** Outside MCP servers the Ask agent may call; the token is read from the `token_env` var. */
	mcp_servers?: { name: string; url: string; token_env?: string | null; allowed_tools?: string[] | null }[];
}

export interface CompanyDetail extends Company {
	config: CompanyConfig;
}

export interface FieldError {
	loc: (string | number)[];
	msg: string;
}

export interface ValidateResult {
	ok: boolean;
	errors: FieldError[];
	/** The file Save would write; only when the draft is valid. */
	yaml: string | null;
	slug_taken: boolean;
	/** Show verbatim under the slug field. */
	slug_taken_detail: string | null;
}

/** What a Settings save requires (`PUT ?dry_run=1`, and the 409 `rebuild_required` detail). */
export interface ConfigChange {
	slug: string;
	changed: boolean;
	rebuild: boolean;
	refetch: string[];
	reasons: string[];
}

export interface GithubTokenCheck {
	token: 'env' | 'gh' | null;
}

export interface GithubRepoCheck {
	exists: boolean;
	/** null when the repo does not exist. */
	private: boolean | null;
}

export interface CompanyRef {
	slug: string;
	name: string;
}

/** GET /api/onboard/github/{owner}/{name}: what the add-a-company dialog shows for a repo. */
export interface RepoLookup {
	/** owner/name as GitHub spells it (as asked, when it does not exist). */
	repo: string;
	exists: boolean;
	private: boolean | null;
	owner_name: string | null;
	/** The suggestion (name, slug, since) is only made for a public repo that exists. */
	name: string | null;
	slug: string | null;
	/** ISO date the window would start at. */
	since: string | null;
	/** The company that already reads this repo. */
	company: CompanyRef | null;
	/** A company that reads another repo of the same owner. */
	owner_company: CompanyRef | null;
}

export interface OnboardRequest {
	repo: string;
	name?: string;
	slug?: string;
}

/** POST /api/onboard/github, 201. `build` is null when the company was saved but did not start. */
export interface OnboardResult {
	company: CompanyDetail;
	build: BuildSnapshot | null;
	build_error: string | null;
}

export interface Stat {
	kind: string;
	type: string;
	count: number;
}

export interface RecentWorkItem {
	uid: string;
	kind: string;
	number: number | null;
	title: string;
	state: string;
	url: string | null;
	author: string | null;
	last_at: string | null;
	systems: string[];
}

export interface SystemSummary {
	system: string;
	system_uid: string;
	path_rule: string | null;
	changes: number;
	people: number;
	owners: string[];
}

export interface PersonActivity {
	login: string;
	person_uid: string;
	display_name: string | null;
	teams: string[];
	prs: number;
	reviews: number;
}

export interface Overview {
	slug: string;
	name: string;
	/** The YAML's window.since, an ISO date. */
	since: string;
	counts: Stat[];
	recent: RecentWorkItem[];
	systems: SystemSummary[];
	people: PersonActivity[];
}

/** How a configured source stands (GET .../sources). blocked: its download fails, so every
 * build fails until fixed; skipped: builds skip it; synced: loaded at least once; never: not yet. */
export type SourceStatus = 'synced' | 'never' | 'skipped' | 'blocked';

export interface KindCount {
	/** Node label: WorkItem, Change, Document, Chunk, Person, Team, System. */
	label: string;
	/** Work items only: pull_request, issue, ticket, thread. */
	kind: string | null;
	count: number;
	/** Work items only: how many in each state. */
	states: Record<string, number>;
}

/** The nodes carrying one `source` label: an adapter type (two folders of one type share it), a
 * JSONL record's own label (`slack_export`), or `derived` (made from links). */
export interface LabelCounts {
	source: string;
	total: number;
	kinds: KindCount[];
}

export interface SourceRow {
	/** The adapter key, which also keys its sync record, like `github:FalkorDB/FalkorDB`. */
	key: string;
	type: string;
	/** The repository, folder or workspace it reads. */
	location: string;
	/** GitHub: what to read; Linear: the teams; else empty. */
	reads: string[];
	/** Has a download step, so syncing this source alone means something. */
	downloads: boolean;
	status: SourceStatus;
	/** Why it is blocked or skipped, with what to do. */
	problem: string | null;
	last_run: string | null;
	/** Records loaded in the last run, not a total. */
	records: number | null;
	/** The newest record read: the next sync starts here. */
	cursor: string | null;
	/** The window moved since the last sync: the next one reloads everything in it. */
	window_changed: boolean;
}

/** A sync record whose key is no longer in the company file. */
export interface SyncRecord {
	key: string;
	adapter: string | null;
	last_run: string | null;
	records: number | null;
	cursor: string | null;
}

export interface SourcesOut {
	slug: string;
	since: string;
	/** The graph exists; false: nothing has been loaded yet. */
	built: boolean;
	sources: SourceRow[];
	/** Biggest first. */
	labels: LabelCounts[];
	leftovers: SyncRecord[];
}

/** A node label as the brain graph spells it; `LABEL_TYPES` maps it to a NodeType. */
export type GraphLabel = 'Person' | 'Team' | 'System' | 'WorkItem' | 'Change' | 'Document';

export const LABEL_TYPES: Record<GraphLabel, NodeType> = {
	Person: 'person',
	Team: 'team',
	System: 'system',
	WorkItem: 'work-item',
	Change: 'change',
	Document: 'document'
};

/** One node of `GET /api/companies/<slug>/graph` (apps/brain/brain/graph_view.py). */
export interface GraphNode {
	uid: string;
	label: GraphLabel;
	title: string | null;
	/** Work item: pull_request, issue, ...; change: feat, fix, ... */
	kind: string | null;
	/** Work item: open, closed, merged. */
	state: string | null;
	number: number | null;
	url: string | null;
	is_bot: boolean;
	/** Comment chunks folded into this node. */
	comments: number;
	/** Links drawn to it in this view. */
	degree: number;
	/** A `Territory.id`. */
	territory: string;
}

export interface GraphEdge {
	source: string;
	rel: string;
	target: string;
}

export interface Territory {
	/** The system's uid, `other` (the smaller systems) or `none` (not linked to code). */
	id: string;
	name: string;
	system_uid: string | null;
	size: number;
	systems: number;
}

export interface GraphView {
	slug: string;
	nodes: GraphNode[];
	edges: GraphEdge[];
	/** Biggest first, then `other`, then `none`. */
	territories: Territory[];
	/** Bot accounts in the graph, shown or not. */
	bots: number;
	bots_shown: boolean;
	/** Comment chunks folded into their work items. */
	comments: number;
}

/** The `get_entity` tool's row: one node's fields (its neighbours come from the graph view). */
export interface Entity {
	uid: string;
	label: string;
	title: string | null;
	kind: string | null;
	state: string | null;
	url: string | null;
	date: string | null;
	body: string;
	neighbour_count: number;
}

// --- Ask (POST /api/companies/{slug}/ask, Server-Sent Events; backend/api/models.py Ask*) -------

/** A node one step touched. `label` is the graph label (Person, Team, System, WorkItem ...). */
export interface WalkNode {
	uid: string;
	label: string;
	title: string;
	url: string | null;
}

/** A relationship one step touched. `inferred`: implied by the rows, not stored in the graph. */
export interface WalkRel {
	from: string;
	to: string;
	/** A stored relationship (AUTHORED) or, when inferred, words (works on). */
	type: string;
	inferred: boolean;
	/** e.g. "score 0.88". */
	note?: string | null;
}

export interface AskStepEvent {
	id: string;
	/** The graph step's number in this answer; null for submit_answer, the answer check. */
	n: number | null;
	tool: string;
	input: Record<string, unknown> | null;
	/** The seq of the Claude response (`AskLlmEvent`) that asked for it. */
	call?: number | null;
}

/**
 * Where a tool call ran: `graph` (a named graph tool), `submit` (the answer check), `mcp` (a tool
 * on an MCP server, through the API's MCP connector) or `server` (an Anthropic server tool).
 */
export type CallKind = 'graph' | 'submit' | 'mcp' | 'server';

/** A tool one Claude response used. MCP and server calls ran already and carry their result. */
export interface AskCall {
	id: string;
	tool: string;
	kind: CallKind;
	/** The MCP server's name. */
	server: string | null;
	input: Record<string, unknown>;
	error?: string | null;
	result?: string | null;
}

export interface AskUsage {
	input: number;
	output: number;
	cache_read: number;
	cache_write: number;
}

/** One Claude response (`llm` event): what it said, its thinking when returned, what it asked for. */
export interface AskLlmEvent {
	seq: number;
	text: string | null;
	thinking: string | null;
	model: string | null;
	stop: string | null;
	ms: number | null;
	usage: AskUsage;
	calls: AskCall[];
}

export interface AskStepDoneEvent extends AskStepEvent {
	ms: number | null;
	/** Rows returned, all of them; `rows` holds the first few. */
	count: number | null;
	error: string | null;
	rows: unknown[];
	nodes: WalkNode[];
	rels: WalkRel[];
}

export interface AskSource {
	uid: string;
	title: string | null;
	url: string | null;
	label: string | null;
	/** The step that first returned it. */
	step: number | null;
}

export interface AskAnswer {
	/** This turn's trace on the server, for a thumbs; null when it was not kept (hide the thumbs). */
	trace_id?: string | null;
	thread_id: string;
	/** Markdown with [n] markers; null when there is no answer (see stop). */
	text: string | null;
	sources: AskSource[];
	path: AskSource[];
	/** Claude's stop reason, or refusal, max_tokens, step_limit, stopped, no_answer. */
	stop: string | null;
	model: string | null;
}

/** A Claude model a question may run on (GET /api/models, backend `ModelOut`). */
export interface ModelInfo {
	id: string;
	name: string;
	/** One line on what it is good for. */
	blurb: string;
	/** Price per token as a multiple of the cheapest model's: 1, 20, 40, 100. */
	cost: number;
	/** An answer can take minutes. */
	slow: boolean;
}

export interface ModelsOut {
	/** Cheapest first. */
	models: ModelInfo[];
	/** The id a question runs on when it names none. */
	default: string;
}

/** One tool call as the page shows it: asked for (running), then done. */
export interface WalkStep extends AskStepEvent {
	status: 'running' | 'done';
	ms?: number | null;
	count?: number | null;
	error?: string | null;
	rows?: unknown[];
	nodes?: WalkNode[];
	rels?: WalkRel[];
}

// --- Chat history (GET /api/companies/{slug}/threads...; brain/agents/history.py) -------------

export type ChatStatus = 'running' | 'done' | 'stopped' | 'failed';

/** A row of the chat list. Times are ISO strings. */
export interface ThreadSummary {
	id: string;
	/** The first question, on one line. */
	title: string;
	created_at: string;
	updated_at: string;
	turns: number;
	last_status: ChatStatus;
}

export interface ThreadPage {
	threads: ThreadSummary[];
	/** Pass as `before` for the next page; null when this was the last. */
	next: number | null;
}

/** A saved tool call: the step shape plus where it ran. */
export interface ChatStep extends AskStepDoneEvent {
	kind: CallKind;
	server: string | null;
	status: string;
	result: string | null;
}

export interface ChatLlmCall {
	seq: number;
	at: string | null;
	model: string | null;
	stop: string | null;
	text: string | null;
	thinking: string | null;
	ms: number | null;
	usage: AskUsage;
}

export interface ChatTurn {
	n: number;
	question: string;
	status: ChatStatus;
	started_at: string;
	ended_at: string | null;
	ms: number | null;
	error: string | null;
	answer: AskAnswer | null;
	calls: ChatLlmCall[];
	steps: ChatStep[];
	rating: Rating | null;
	note: string | null;
}

/** A whole chat, as the Ask page reopens it. */
export interface Thread {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	last_status: ChatStatus;
	turns: ChatTurn[];
}

/** A thumbs on one answer (POST .../traces/{trace_id}/feedback); null takes it back. */
export type Rating = 'up' | 'down';

export interface Feedback {
	trace_id: string;
	rating: Rating | null;
	note: string | null;
}

// --- Agent activity (GET /api/companies/{slug}/activity; agents/activity.py) -----------------

/** One tool call of a run, with the company-graph nodes it touched. */
export interface ActivityStep {
	/** 1-based, in the order the agent ran them. */
	n: number;
	/** `brain` for Ask; `keeper`, `pm`, `qa` once Keeper reviews are listed. */
	actor: string;
	tool: string;
	kind: CallKind;
	input: Record<string, unknown>;
	status: 'running' | 'done' | 'failed';
	count: number | null;
	error: string | null;
	/** brain_<slug> uids, in the order the step returned them. */
	touched: string[];
}

/** One run of one agent: today an Ask turn. Times are ISO strings. */
export interface ActivityRun {
	/** `ask:<thread id>:<turn n>`. */
	id: string;
	source: 'ask';
	actor: string;
	/** What the run was for: the question. */
	title: string;
	status: ChatStatus;
	started_at: string;
	ended_at: string | null;
	/** An Ask run reopens in its chat. */
	thread_id: string | null;
	steps: ActivityStep[];
}

export interface Activity {
	/** Newest first. */
	runs: ActivityRun[];
	/** Some run is still going, so the page keeps watching. */
	running: boolean;
}
