/**
 * The rules of the Settings page that do not need a browser: whether the draft differs from the
 * saved config and in which tabs, what the save bar says a save will cost, what the rebuild dialog
 * says, and what a refused save means.
 *
 * Why: "Save" must stay off until something changed, and a save the server refuses (a rebuild is
 * needed, a build is running, the draft is invalid) must each lead to its own message. Pure
 * functions let vitest cover every case; the page only draws what they return.
 */
import { ApiError, describeError } from './api/client';
import { SECTIONS, SECTION_KEYS, STEP_NAMES, cleanDraft, type Section } from './onboarding';
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

/** The sections (Settings tabs) whose part of the file differs from the saved config, in tab order. */
export function changedSections(draft: CompanyConfig, loaded: CompanyConfig): Section[] {
	const a = JSON.parse(canonical(draft)) as Record<string, unknown>;
	const b = JSON.parse(canonical(loaded)) as Record<string, unknown>;
	return SECTIONS.filter((s) =>
		SECTION_KEYS[s].some((key) => JSON.stringify(a[key]) !== JSON.stringify(b[key]))
	);
}

/** "Company and Sources": section names joined for a sentence. */
function sectionList(sections: Section[]): string {
	const names = sections.map((s) => STEP_NAMES[s]);
	return names.length < 2 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}

/** The save bar's first line: where the unsaved edits are. */
export function unsavedLine(sections: Section[]): string {
	return sections.length === 0 ? 'Unsaved changes.' : `Unsaved changes in ${sectionList(sections)}.`;
}

export interface SaveCost {
	/** The Save button's words: it names a rebuild before it is pressed. */
	label: 'Save' | 'Save and rebuild';
	/** What the save will do, in one sentence. */
	line: string;
	rebuild: boolean;
}

/** What saving the draft will do, from the server's dry run; null while it is not known. */
export function saveCost(change: ConfigChange | null): SaveCost | null {
	if (!change || !change.changed) return null;
	const list = change.refetch.join(', ');
	if (change.rebuild) {
		return {
			label: 'Save and rebuild',
			rebuild: true,
			line:
				change.refetch.length > 0
					? `Saving downloads ${list} again and rebuilds the graph.`
					: 'Saving rebuilds the graph from the data already downloaded.'
		};
	}
	return {
		label: 'Save',
		rebuild: false,
		line:
			change.refetch.length > 0
				? `Saving starts a build to download ${list}.`
				: 'Saves at once. The graph is not touched.'
	};
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
	return { kind: 'other', message: describeError(error) };
}

/** The line next to the button after a save that needed no rebuild. */
export function syncLine(refetch: string[]): string {
	return refetch.length > 0
		? `Saved. A build started to download ${refetch.join(', ')}.`
		: 'Saved';
}

export interface SaveReason {
	text: string;
	/** The tab that holds the problem, when there is one to go to. */
	section: Section | null;
}

const sectionNamed = (name: string): Section | null =>
	SECTIONS.find((s) => STEP_NAMES[s] === name) ?? null;

/**
 * Why Save is shut, and which tab to go to. The shared gate words its reasons for the wizard's
 * steps ("Sources (step 2): ... to continue."); Settings shows the sections as tabs.
 */
export function settingsReason(reason: string | null): SaveReason | null {
	if (reason === null) return null;
	const errors = /^Fix the errors in (.+) \(step \d\) first\.$/.exec(reason);
	if (errors) return { text: `Fix the fields marked in ${errors[1]}.`, section: sectionNamed(errors[1]) };
	if (reason === 'Fix the fields marked above.') {
		const last = SECTIONS[SECTIONS.length - 1];
		return { text: `Fix the fields marked in ${STEP_NAMES[last]}.`, section: last };
	}
	const step = /^(.+) \(step \d\): (.*)$/.exec(reason);
	const text = (step ? step[2] : reason).replace(/ to continue\.$/, ' to save.');
	return { text, section: step ? sectionNamed(step[1]) : null };
}
