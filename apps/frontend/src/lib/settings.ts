/**
 * The rules of the Settings page that do not need a browser: whether the draft differs from the
 * saved config, what the rebuild dialog says, and what a refused save means.
 *
 * Why: "Save" must stay off until something changed, and a save the server refuses (a rebuild is
 * needed, a build is running, the draft is invalid) must each lead to its own message. Pure
 * functions let vitest cover every case; the page only draws what they return.
 */
import { ApiError } from './api/client';
import { cleanDraft } from './onboarding';
import type { CompanyConfig, ConfigChange, FieldError } from './types';

/** `value` with object keys sorted, so two equal configs print the same text. */
function stable(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(stable);
	if (value !== null && typeof value === 'object') {
		return Object.fromEntries(
			Object.entries(value as Record<string, unknown>)
				.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
				.map(([key, v]) => [key, stable(v)])
		);
	}
	return value;
}

/** The config as it would be saved: cleaned, with the blocks the form always adds, keys sorted. */
function canonical(config: CompanyConfig): string {
	const out = cleanDraft(config);
	out.systems = { rules: [], fallback: 'depth_2', ignore: [], ...out.systems };
	out.people = { bots: [], aliases: {}, ...out.people };
	return JSON.stringify(stable(out));
}

/** True when saving `draft` would change something. */
export function isDirty(draft: CompanyConfig, loaded: CompanyConfig): boolean {
	return canonical(draft) !== canonical(loaded);
}

export interface RebuildDialog {
	title: string;
	reasons: string[];
	explanation: string;
	/** The "downloaded again" sentence, or null when nothing is fetched again. */
	refetch: string | null;
}

/** "Acme Labs'" and "Acme's": the possessive the dialog title needs. */
const possessive = (name: string) => (name.endsWith('s') ? `${name}'` : `${name}'s`);

/** What the confirm dialog says about a save that rebuilds the graph. */
export function rebuildDialog(name: string, change: ConfigChange): RebuildDialog {
	return {
		title: `Rebuild ${possessive(name)} graph?`,
		reasons: change.reasons,
		explanation:
			'The graph is emptied and rebuilt from the cached data. Answers are unavailable until it finishes.',
		refetch:
			change.refetch.length > 0
				? `These sources are downloaded again: ${change.refetch.join(', ')}`
				: null
	};
}

export type SaveProblem =
	| { kind: 'rebuild'; change: ConfigChange }
	| { kind: 'running' }
	| { kind: 'invalid'; errors: FieldError[] }
	| { kind: 'other'; message: string };

/** What a failed save or dry run means. */
export function classifySaveError(error: unknown): SaveProblem {
	if (error instanceof ApiError) {
		const detail = error.detail;
		if (error.status === 409) {
			if (detail !== null && typeof detail === 'object' && 'rebuild_required' in detail) {
				return {
					kind: 'rebuild',
					change: (detail as { rebuild_required: ConfigChange }).rebuild_required
				};
			}
			if (typeof detail === 'string') return { kind: 'running' };
		}
		if (error.status === 422 && Array.isArray(detail)) {
			return { kind: 'invalid', errors: detail as FieldError[] };
		}
	}
	return { kind: 'other', message: error instanceof Error ? error.message : String(error) };
}

/** The line next to the button after a save that needed no rebuild. */
export function syncLine(refetch: string[]): string {
	return refetch.length > 0
		? `Saved. A build started to download ${refetch.join(', ')}.`
		: 'Saved';
}

/**
 * The footer line for a save that is shut. The shared gate words its reasons for the wizard's
 * steps ("Sources (step 2): ... to continue."); Settings shows every section on one page.
 */
export function settingsReason(reason: string | null): string | null {
	if (reason === null) return null;
	if (/^Fix the errors in /.test(reason)) return 'Fix the fields marked above.';
	return reason.replace(/^[^:]*\(step \d\): /, '').replace(/ to continue\.$/, ' to save.');
}
