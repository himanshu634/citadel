/**
 * Where a reference in the UI opens: a PR or issue number, a commit, a document or a file path.
 * A record's own `url` always wins (GitHub, Linear, example.com for the synthetic company). Only
 * GitHub uids (`github:<owner>/<name>:<kind>:<id>`) and refs the model writes in an answer
 * (`#123`, `owner/name#123`, `path/to/file.py:42`) make a github.com url, and only when the repo
 * is known; nothing else is guessed. Every url passes `safeUrl`: ingested data is not trusted.
 */

const GITHUB = 'https://github.com';
const REPO = /^[\w.-]+\/[\w.-]+$/;

/** The url if it is http(s), else null (a `javascript:` url in ingested data never becomes a link). */
export function safeUrl(url: string | null | undefined): string | null {
	if (!url) return null;
	try {
		const u = new URL(url);
		return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
	} catch {
		return null;
	}
}

/** The site a url opens, as a button says it: "GitHub", "Linear", else the host. */
export function siteName(url: string): string {
	let host: string;
	try {
		host = new URL(url).hostname.replace(/^www\./, '');
	} catch {
		return 'source';
	}
	if (host === 'github.com') return 'GitHub';
	if (host === 'linear.app') return 'Linear';
	return host;
}

const path = (p: string) => p.split('/').map(encodeURIComponent).join('/');

export function issueUrl(repo: string, n: number): string {
	// GitHub sends /issues/<n> on to /pull/<n> when the number is a PR.
	return `${GITHUB}/${repo}/issues/${n}`;
}

/**
 * A file or folder on the default branch (`HEAD`, so the branch name is not needed), at a line
 * or a range. A rendered file (Markdown) shows its lines only in plain view.
 */
export function fileUrl(repo: string, file: string, line?: number, end?: number): string {
	const dir = file.endsWith('/');
	const clean = file.replace(/^\.?\//, '').replace(/\/$/, '');
	let url = `${GITHUB}/${repo}/${dir ? 'tree' : 'blob'}/HEAD/${path(clean)}`;
	if (line !== undefined && !dir) {
		if (/\.(md|markdown|rst|adoc)$/i.test(clean)) url += '?plain=1';
		url += `#L${line}${end !== undefined && end > line ? `-L${end}` : ''}`;
	}
	return url;
}

/** The repo (`owner/name`) a GitHub uid belongs to, else null. */
export function repoOfUid(uid: string): string | null {
	const m = /^github:([^:]+):/.exec(uid);
	return m && REPO.test(m[1]) ? m[1] : null;
}

/** The github.com page a GitHub uid stands for: PR, issue, commit or document; else null. */
export function uidUrl(uid: string): string | null {
	const m = /^github:([^:]+):(pr|issue|commit|doc):(.+)$/.exec(uid);
	if (!m || !REPO.test(m[1])) return null;
	const [, repo, kind, id] = m;
	if (kind === 'pr' && /^\d+$/.test(id)) return `${GITHUB}/${repo}/pull/${id}`;
	if (kind === 'issue' && /^\d+$/.test(id)) return issueUrl(repo, Number(id));
	if (kind === 'commit' && /^[0-9a-f]{4,40}$/i.test(id)) return `${GITHUB}/${repo}/commit/${id}`;
	if (kind === 'doc') return fileUrl(repo, id);
	return null;
}

/** Where a node opens: its own url when it has a safe one, else one made from a GitHub uid. */
export function refUrl(uid: string | null | undefined, url?: string | null): string | null {
	return safeUrl(url) ?? (uid ? uidUrl(uid) : null);
}

/** The number a work item's uid ends in (`x:pr:12`, `x:issue:12`), else null. */
export function numberOfUid(uid: string): number | null {
	const m = /:(?:pr|issue):(\d+)$/.exec(uid);
	return m ? Number(m[1]) : null;
}

/** What an answer's references resolve against: the nodes its walk saw, and the company's repo. */
export interface RefContext {
	/** Work item urls by number; null when two items share the number (two repos). */
	numbers: Map<number, string | null>;
	/** Document urls by repo-relative path. */
	files: Map<string, string>;
	/** The one GitHub repo bare refs belong to, when there is exactly one. */
	repo: string | null;
}

/** A thing a walk saw: a node, a source or a tool row with a uid. */
interface Seen {
	uid?: unknown;
	url?: unknown;
	number?: unknown;
	path?: unknown;
}

/**
 * The context for one answer's refs: every uid'd object in `seen` (walk nodes, sources, tool rows,
 * searched to any depth), and `repos`, the company's GitHub repos. Bare refs use the one repo
 * there is: the company's when it reads exactly one, else the walk's when it saw exactly one.
 */
export function refContext(seen: unknown[], repos: string[] = []): RefContext {
	const numbers = new Map<number, string | null>();
	const files = new Map<string, string>();
	const walked = new Set<string>();
	const visit = (v: unknown) => {
		if (Array.isArray(v)) return v.forEach(visit);
		if (!v || typeof v !== 'object') return;
		const o = v as Seen;
		if (typeof o.uid === 'string') {
			const uid = o.uid;
			const url = refUrl(uid, typeof o.url === 'string' ? o.url : null);
			const repo = repoOfUid(uid);
			if (repo) walked.add(repo);
			const n = typeof o.number === 'number' ? o.number : numberOfUid(uid);
			if (url && n !== null) {
				const had = numbers.get(n);
				if (had === undefined) numbers.set(n, url);
				else if (had !== url) numbers.set(n, null);
			}
			const doc = /:doc:(.+)$/.exec(uid)?.[1] ?? (typeof o.path === 'string' ? o.path : null);
			if (url && doc && !files.has(doc)) files.set(doc, url);
		}
		for (const x of Object.values(o)) if (x && typeof x === 'object') visit(x);
	};
	seen.forEach(visit);
	const known = repos.filter((r) => REPO.test(r));
	const repo = known.length === 1 ? known[0] : known.length === 0 && walked.size === 1 ? [...walked][0] : null;
	return { numbers, files, repo };
}

/** The empty context: refs link only when they name their repo (`owner/name#12`). */
export const NO_REFS: RefContext = { numbers: new Map(), files: new Map(), repo: null };

/** Where `#n` (or `owner/name#n` when `repo` is given) opens, else null. */
export function numberUrl(n: number, ctx: RefContext, repo?: string): string | null {
	if (repo) return REPO.test(repo) ? issueUrl(repo, n) : null;
	const known = ctx.numbers.get(n);
	if (known) return known;
	if (known === null) return null; // two items have this number: say nothing rather than guess
	return ctx.repo ? issueUrl(ctx.repo, n) : null;
}

/** Extensions that make a bare word a file name; `token.verify` stays code, `token.py` links. */
const FILE_EXT = new Set(
	(
		'c cc cpp cxx h hh hpp go rs py pyi rb java kt kts scala swift m mm cs fs php pl lua r jl ex exs erl hs ml ' +
		'js mjs cjs jsx ts tsx svelte vue astro html htm css scss sass less ' +
		'json jsonc yaml yml toml ini cfg conf env lock xml csv tsv proto graphql gql cypher sql ' +
		'sh bash zsh fish ps1 bat cmake mk gradle tf hcl nix ' +
		'md markdown mdx rst adoc txt'
	).split(' ')
);
const FILE_NAMES = new Set(['Makefile', 'Dockerfile', 'CODEOWNERS', 'LICENSE', 'Rakefile', 'Gemfile', 'Justfile']);

export interface CodeRef {
	file: string;
	line?: number;
	end?: number;
}

/**
 * A file path (with an optional `:line` or `:line-end`, or `#Lline`) as the model writes one, else
 * null. A path needs a known extension or file name; a folder needs a `/` in it and a trailing `/`.
 * Urls, globs, `owner/name` and words like `identity` are not paths.
 */
export function codeRef(text: string): CodeRef | null {
	const m = /^((?:\.?\/)?[\w@.+-]+(?:\/[\w@.+-]+)*\/?)(?::(\d+)(?:-(\d+))?|#L(\d+)(?:-L(\d+))?)?$/.exec(text.trim());
	if (!m) return null;
	const file = m[1];
	const line = m[2] ?? m[4];
	const end = m[3] ?? m[5];
	const at = { ...(line ? { line: Number(line) } : {}), ...(end ? { end: Number(end) } : {}) };
	if (file.endsWith('/')) return file.slice(0, -1).includes('/') && !line ? { file } : null;
	const name = file.split('/').at(-1) ?? '';
	const ext = /\.([A-Za-z0-9]+)$/.exec(name)?.[1]?.toLowerCase();
	if ((ext && FILE_EXT.has(ext) && name.length > ext.length + 1) || FILE_NAMES.has(name)) return { file, ...at };
	return null;
}

/** Where a file path opens: the document the walk saw at that path, else the file in the repo. */
export function codeUrl(ref: CodeRef, ctx: RefContext): string | null {
	const clean = ref.file.replace(/^\.?\//, '');
	const doc = ctx.files.get(clean);
	if (doc && ref.line === undefined) return doc;
	return ctx.repo ? fileUrl(ctx.repo, clean, ref.line, ref.end) : null;
}

/** A run of text: plain, or a reference with where it opens. */
export type TextRun = { text: string; href?: string };

/**
 * `#12`, `owner/name#12` and file paths with a `/` in plain text (`src/auth/token.py:42`), split
 * out as links where they resolve. `&#12;`, `page#12` and `issue#12` stay text: a ref starts a word.
 */
const TEXT_REF =
	/(?<url>\b[a-z][a-z0-9+.-]*:\/\/\S+)|(?<![\w&/#])(?:(?<repo>[\w.-]+\/[\w.-]+)?#(?<n>\d+)\b|(?<path>(?:[\w@.+-]+\/)+[\w@.+-]+(?::\d+(?:-\d+)?)?))/gi;

export function textRuns(text: string, ctx: RefContext): TextRun[] {
	const out: TextRun[] = [];
	let at = 0;
	const push = (t: string) => {
		const last = out.at(-1);
		if (last && last.href === undefined) last.text += t;
		else out.push({ text: t });
	};
	for (const m of text.matchAll(TEXT_REF)) {
		const g = m.groups ?? {};
		if (g.url) continue; // a url in the text is read as text, never taken apart
		let href: string | null = null;
		let ref = m[0];
		if (g.n !== undefined) href = numberUrl(Number(g.n), ctx, g.repo);
		else {
			ref = ref.replace(/[.,;:]+$/, ''); // a path at the end of a sentence
			const code = codeRef(ref);
			href = code ? codeUrl(code, ctx) : null;
		}
		if (!href) continue;
		if (m.index > at) push(text.slice(at, m.index));
		out.push({ text: ref, href });
		at = m.index + ref.length;
	}
	if (at < text.length) push(text.slice(at));
	return out;
}

/** Runs for text that names nodes by label (a step's sentence): each label is linked to its url. */
export function labelRuns(text: string, refs: { label: string; href: string | null }[]): TextRun[] {
	let runs: TextRun[] = [{ text }];
	for (const { label, href } of refs) {
		if (!href || !label) continue;
		runs = runs.flatMap((run) => {
			if (run.href !== undefined) return [run];
			const i = run.text.indexOf(label);
			if (i < 0) return [run];
			return [
				...(i > 0 ? [{ text: run.text.slice(0, i) }] : []),
				{ text: label, href },
				...(i + label.length < run.text.length ? [{ text: run.text.slice(i + label.length) }] : [])
			];
		});
	}
	return runs;
}

/** The GitHub repos (`owner/name`) among a company's sources. */
export function githubRepos(sources: { type: string; location: string }[]): string[] {
	return sources.filter((s) => s.type === 'github' && REPO.test(s.location)).map((s) => s.location);
}
