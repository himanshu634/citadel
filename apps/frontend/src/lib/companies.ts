/**
 * Company helpers: the rail's monogram, the slug a name suggests, and the route to keep when the
 * user switches company.
 *
 * Why: these are pure and shared by the rail, onboarding and the switcher, so they live apart from
 * the components and are unit-tested (spec 5.2).
 */

import type { CompanyStatus } from './types';

/** Same pattern as the backend's SLUG_RE (apps/backend/brain/config.py). */
const SLUG = /^[a-z0-9][a-z0-9_]*$/;

function base(name: string): string {
	const words = name.trim().split(/\s+/).filter(Boolean);
	if (words.length === 0) return '?';
	if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
	const chars = [...words[0]];
	return chars[0].toUpperCase() + (chars[1] ?? '').toLowerCase();
}

/** The first letter plus the next letter of the name that gives a monogram nobody has yet. */
function unique(name: string, taken: Set<string>): string {
	const letters = [...name].filter((c) => /\p{L}|\p{N}/u.test(c));
	const first = (letters[0] ?? '?').toUpperCase();
	for (const c of letters.slice(1)) {
		const candidate = first + c.toLowerCase();
		if (!taken.has(candidate)) return candidate;
	}
	for (let n = 2; ; n++) {
		const candidate = first + n;
		if (!taken.has(candidate)) return candidate;
	}
}

/**
 * The 1-2 letter label for the company at `index`: initials of the first two words, else the first
 * two letters in title case ("Acme Labs" -> "AL", "FalkorDB" -> "Fa"). `names` is every company
 * in rail order; a company whose monogram an earlier one already has gets its first letter plus the
 * next letter that makes it unique ("Fabric" after "FalkorDB" -> "Fb"). It takes a position, not a
 * name, because two companies can share a display name and each still needs its own monogram.
 */
export function monogram(names: string[], index: number): string {
	const taken = new Set<string>();
	let own = '?';
	for (const n of names.slice(0, index + 1)) {
		own = base(n);
		if (own === '?') continue;
		if (taken.has(own)) own = unique(n, taken);
		taken.add(own);
	}
	return own;
}

/** The slug a company name suggests, or '' when nothing valid is left. */
export function slugify(name: string): string {
	const slug = name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '_')
		.replace(/^_+|_+$/g, '');
	return SLUG.test(slug) ? slug : '';
}

/**
 * Where to go when the user picks another company: the same section (`/c/a/settings` ->
 * `/c/b/settings`), except the build page, which belongs to one build, and any route outside
 * `/c/<slug>/`: those land on the new company's home. A company whose config is `invalid` has no
 * settings or build to open (its settings cannot load), so it always lands on its overview, which
 * shows the config error (spec 5.2: the overview when the section does not exist).
 */
export function sectionPath(pathname: string, toSlug: string, toStatus?: CompanyStatus): string {
	const home = `/c/${toSlug}/`;
	const match = pathname.match(/^\/c\/[^/]+\/([^/]+)/);
	if (!match || match[1] === 'build' || toStatus === 'invalid') return home;
	return `/c/${toSlug}/${match[1]}`;
}
