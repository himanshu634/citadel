/**
 * The HTTP client for the brain API (apps/backend/backend/api), called through `/api`.
 *
 * Why: one place knows the routes, the query flags and how errors look, so pages and stores deal
 * in typed values and `ApiError`. In dev, vite proxies `/api` to `make api`. The live event
 * streams (SSE) are separate and not here.
 */
import type {
	BuildSnapshot,
	Company,
	CompanyConfig,
	CompanyDetail,
	ConfigChange,
	Feedback,
	GithubRepoCheck,
	GithubTokenCheck,
	LinearKeyCheck,
	Entity,
	GraphView,
	ModelsOut,
	OnboardRequest,
	OnboardResult,
	Overview,
	Rating,
	RepoLookup,
	Thread,
	ThreadPage,
	ThreadSummary,
	ValidateResult
} from '../types';

/** A non-2xx answer. `detail` is the body's `detail` (a string, FieldError[] or an object). */
export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly detail: unknown
	) {
		super(typeof detail === 'string' ? detail : `API error ${status}`);
		this.name = 'ApiError';
	}
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const init: RequestInit = { method };
	if (body !== undefined) {
		init.headers = { 'Content-Type': 'application/json' };
		init.body = JSON.stringify(body);
	}
	const response = await fetch(`/api${path}`, init);
	const text = await response.text();
	let payload: unknown = text;
	try {
		payload = text ? JSON.parse(text) : undefined;
	} catch {
		// Not JSON (a proxy's error page): keep the text as the detail.
	}
	if (!response.ok) {
		const detail =
			payload !== null && typeof payload === 'object' && 'detail' in payload
				? (payload as { detail: unknown }).detail
				: payload;
		throw new ApiError(response.status, detail);
	}
	return payload as T;
}

const company = (slug: string) => `/companies/${encodeURIComponent(slug)}`;

export const api = {
	companies: () => request<Company[]>('GET', '/companies'),
	/** The Claude models an Ask question may run on, and the default. */
	models: () => request<ModelsOut>('GET', '/models'),
	/** A thumbs on one Ask answer (its `trace_id`); `rating` null takes it back. 404: no such answer. */
	feedback: (slug: string, traceId: string, rating: Rating | null, note?: string) =>
		request<Feedback>('POST', `${company(slug)}/traces/${encodeURIComponent(traceId)}/feedback`, {
			rating,
			note: note ?? null
		}),
	/** The chat list, most recently active first; pass the page's `next` as `before` for more. */
	threads: (slug: string, before?: number | null) =>
		request<ThreadPage>('GET', `${company(slug)}/threads${before ? `?before=${before}` : ''}`),
	/** One chat with every turn, Claude response and tool call. 404: no such chat. */
	thread: (slug: string, id: string) => request<Thread>('GET', `${company(slug)}/threads/${encodeURIComponent(id)}`),
	/** Delete a chat and its checkpoints. 409 while it is answering. */
	deleteThread: (slug: string, id: string) =>
		request<void>('DELETE', `${company(slug)}/threads/${encodeURIComponent(id)}`),
	/** The chats that touched or cited one node of the company graph. */
	refThreads: (slug: string, uid: string) =>
		request<ThreadSummary[]>('GET', `${company(slug)}/refs/${encodeURIComponent(uid)}/threads`),
	company: (slug: string) => request<CompanyDetail>('GET', company(slug)),
	/** Check a draft on every form change; writes nothing. */
	validate: (draft: CompanyConfig) => request<ValidateResult>('POST', '/companies/validate', draft),
	/** 201 CompanyDetail; 409 (string detail) when the slug is taken; 422 (FieldError[]). */
	create: (draft: CompanyConfig) => request<CompanyDetail>('POST', '/companies', draft),
	/**
	 * Settings save. `dryRun` reports what the change requires (ConfigChange); `rebuild` saves and
	 * starts the rebuild (BuildSnapshot); otherwise it saves (CompanyDetail), or throws ApiError 409
	 * when a rebuild is required (see `rebuildRequired`) or a build is running.
	 */
	update: ((slug: string, cfg: CompanyConfig, opts: { dryRun?: boolean; rebuild?: boolean } = {}) => {
		const query = opts.dryRun ? '?dry_run=1' : opts.rebuild ? '?rebuild=1' : '';
		return request('PUT', `${company(slug)}${query}`, cfg);
	}) as {
		(slug: string, cfg: CompanyConfig, opts: { dryRun: true }): Promise<ConfigChange>;
		(slug: string, cfg: CompanyConfig, opts: { rebuild: true }): Promise<BuildSnapshot>;
		(slug: string, cfg: CompanyConfig, opts?: { dryRun?: boolean; rebuild?: boolean }): Promise<CompanyDetail>;
	},
	/** `full` ignores the sync cursors and loads everything in the window again. */
	startBuild: (slug: string, full = false) =>
		request<BuildSnapshot>('POST', `${company(slug)}/builds`, { full }),
	/** The running build, else the last one. 404 when the company never built. */
	currentBuild: (slug: string) => request<BuildSnapshot>('GET', `${company(slug)}/builds/current`),
	stopBuild: (slug: string) => request<BuildSnapshot>('DELETE', `${company(slug)}/builds/current`),
	/** 503 while FalkorDB is down. */
	overview: (slug: string) => request<Overview>('GET', `${company(slug)}/overview`),
	/** The whole graph for the Graph page; `bots` adds the bot accounts and their links. */
	graph: (slug: string, bots = false) =>
		request<GraphView>('GET', `${company(slug)}/graph${bots ? '?bots=true' : ''}`),
	/** One node's fields (the `get_entity` tool); null when the graph has no such node. */
	entity: (slug: string, uid: string) =>
		request<{ rows: Entity[] }>('POST', `${company(slug)}/tools/get_entity`, {
			uid,
			limit: 1
		}).then((r) => r.rows[0] ?? null),
	githubToken: () => request<GithubTokenCheck>('GET', '/checks/github'),
	/** 424 without a token, 429 when rate limited, 502 when GitHub fails. */
	githubRepo: (owner: string, name: string) =>
		request<GithubRepoCheck>(
			'GET',
			`/checks/github/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
		),
	/** Whether LINEAR_API_KEY is set; read once per API process, so a new key needs a restart. */
	linearKey: () => request<LinearKeyCheck>('GET', '/checks/linear'),
	/** The add-a-company dialog's lookup. 424 without a token, 429 rate limited, 502 GitHub failed. */
	lookupRepo: (owner: string, name: string) =>
		request<RepoLookup>(
			'GET',
			`/onboard/github/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
		),
	/**
	 * Create a company from one public repo and start its first build. 422 `{code: 'private_repo' |
	 * 'not_found'}` or FieldError[]; 409 `{code: 'repo_taken', slug, name}` or `{code: 'slug_taken'}`.
	 */
	onboard: (body: OnboardRequest) => request<OnboardResult>('POST', '/onboard/github', body)
};

/** Said when nothing answers at `/api`: the API is not running, or the dev proxy has no one behind it. */
const API_DOWN = "The Citadel API isn't answering. Start it with make api, then try again.";

/**
 * One sentence for any failed API call, so every page words "the API is down" the same way.
 * The API's own text (`detail` as a string) wins; 503 means FalkorDB is down behind a live API;
 * other 4xx are refusals; anything else (a network `TypeError`, a 5xx with no body from a dev
 * proxy with nothing behind it) means the API is not answering.
 */
export function describeError(e: unknown): string {
	if (e instanceof ApiError) {
		if (typeof e.detail === 'string' && e.detail !== '') return e.detail;
		if (e.status === 503) return "FalkorDB isn't answering. Start it with make up, then try again.";
		if (e.status >= 400 && e.status < 500) return `The API refused the request (${e.status}).`;
	}
	return API_DOWN;
}

/** The 409 of a Settings save that needs a rebuild first, else null. */
export function rebuildRequired(error: unknown): ConfigChange | null {
	if (!(error instanceof ApiError) || error.status !== 409) return null;
	const detail = error.detail;
	if (detail !== null && typeof detail === 'object' && 'rebuild_required' in detail) {
		return (detail as { rebuild_required: ConfigChange }).rebuild_required;
	}
	return null;
}
