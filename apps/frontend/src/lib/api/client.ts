/**
 * The HTTP client for the brain API (apps/backend/brain/api), called through `/api`.
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
	GithubRepoCheck,
	GithubTokenCheck,
	Overview,
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
	githubToken: () => request<GithubTokenCheck>('GET', '/checks/github'),
	/** 424 without a token, 429 when rate limited, 502 when GitHub fails. */
	githubRepo: (owner: string, name: string) =>
		request<GithubRepoCheck>(
			'GET',
			`/checks/github/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
		)
};

/** The 409 of a Settings save that needs a rebuild first, else null. */
export function rebuildRequired(error: unknown): ConfigChange | null {
	if (!(error instanceof ApiError) || error.status !== 409) return null;
	const detail = error.detail;
	if (detail !== null && typeof detail === 'object' && 'rebuild_required' in detail) {
		return (detail as { rebuild_required: ConfigChange }).rebuild_required;
	}
	return null;
}
