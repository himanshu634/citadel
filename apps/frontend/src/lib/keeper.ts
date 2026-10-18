/**
 * The Keeper in the Systems page's rail: the words for its claims, log and reviews, and how an
 * approval is checked and how its errors read.
 *
 * Why: the ledger keeps codes (`high_impact_system`, `claim_queued`, `review:<id>: manual,
 * budget 3`); a lead reads sentences. Pure: no Svelte, no fetch.
 */
import { ApiError, describeError } from './api/client';
import { shortUid } from './walk';
import type { ActivityRun, ClaimKind, ClaimStatus, ClaimTrail, FieldError, LogEntry, Review, TrailJob } from './types';

const REASONS: Record<string, string> = {
	replaces_claim: 'it replaces an earlier Keeper update',
	high_impact_system: 'it touches a high-impact system',
	no_source_evidence: 'no commit, PR, ticket or doc is behind it',
	from_person: 'a person told it in Ask'
};

const words = (code: string) => code.replaceAll('_', ' ');

/** One reason a claim waits for a lead, as a clause. */
export function reasonWords(code: string): string {
	return REASONS[code] ?? words(code);
}

/** "a, b and c". */
function list(parts: string[]): string {
	return parts.length < 2 ? (parts[0] ?? '') : `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`;
}

/** Why a pending claim needs a lead, in one sentence. */
export function criticalLine(reasons: string[]): string {
	return reasons.length ? `Needs a lead because ${list(reasons.map(reasonWords))}.` : 'Needs a lead.';
}

/** One reason a claim waits for a lead, as the review page lists it: a heading and what it means. */
export interface ReasonRow {
	code: string;
	title: string;
	detail: string;
}

const REASON_ROWS: Record<string, Omit<ReasonRow, 'code'>> = {
	replaces_claim: {
		title: 'It replaces an earlier claim',
		detail: 'Approving it retires the Keeper update it replaces.'
	},
	high_impact_system: {
		title: 'It touches a high-impact system',
		detail: 'The system is in the top quarter by how often it changes together with others.'
	},
	no_source_evidence: {
		title: 'No source is behind it',
		detail: 'No commit, PR, ticket or doc says it: the agents worked it out.'
	},
	from_person: {
		title: 'A person said it in Ask',
		detail: 'It comes from a reply someone gave in Ask, so a lead decides.'
	}
};

/** Why a pending claim needs a lead, one row per reason; a code without words reads as itself. */
export function reasonRows(codes: string[]): ReasonRow[] {
	if (!codes.length) return [{ code: 'lead', title: 'It needs a lead', detail: 'The Keeper does not write it on its own.' }];
	return codes.map((code) => ({ code, ...(REASON_ROWS[code] ?? { title: words(code), detail: '' }) }));
}

/** A decided claim in one or two words, from the claim the server returned. */
export function decidedTag(decision: 'approve' | 'reject', status: ClaimStatus): { text: string; tone: 'success' | 'neutral' | 'warning' } {
	if (decision === 'reject') return { text: 'Rejected', tone: 'neutral' };
	if (status === 'conflicts_with_source') return { text: 'Approved, sources differ', tone: 'warning' };
	if (status === 'stale') return { text: 'Approved, not added', tone: 'warning' };
	return { text: 'Approved', tone: 'success' };
}

export const CLAIM_KINDS: Record<ClaimKind, string> = {
	owner: 'Owner',
	expert: 'Expert',
	decision: 'Decision',
	fact: 'Fact',
	link: 'Link'
};

/**
 * Who wrote a log line: the Keeper for itself and its auto-accepts, a role for its agent
 * (`agent:pm` -> pm), Ask for a reply a person gave there, else the name as logged.
 */
export function whoName(actor: string): string {
	const who = actor.startsWith('agent:') ? actor.slice('agent:'.length) : actor;
	if (who === 'ask') return 'Ask';
	if (who === 'archivist') return 'Archivist';
	return who === 'auto' || who === 'keeper' ? 'Keeper' : who;
}

/**
 * The log lines the rail shows: the newest `limit`, without the runner's `episode` lines (one
 * per job, repeating the consult or decision logged next to it).
 */
export function railLog(entries: LogEntry[], limit: number): LogEntry[] {
	return entries.filter((e) => e.action !== 'episode').slice(0, limit);
}

/** Each log action as what its actor did. */
const ACTIONS: Record<string, string> = {
	gap_opened: 'opened a gap',
	consult_answered: 'answered a consult',
	claim_queued: 'asked a lead to approve a claim',
	claim_written: 'wrote a claim',
	claim_approved: 'approved a claim',
	claim_rejected: 'rejected a claim',
	claim_superseded: 'marked a claim superseded',
	claim_stale: 'marked a claim stale',
	claim_conflicts_with_source: 'found a claim conflicts with the sources',
	claim_approval_failed: 'could not approve a claim',
	gap_dismissed: 'dismissed a gap',
	needs_person: 'said a gap needs a person',
	gap_released: 'put a gap back',
	follow_up_opened: 'opened a follow-up',
	follow_up_skipped: 'opened no follow-up for a claim',
	episode: 'finished a job',
	review_start: 'started a review',
	review_done: 'finished a review',
	review_stopped: 'stopped a review',
	review_failed: 'saw a review fail',
	review_skipped: 'skipped a review',
	archive_requested: 'asked the Archivist for older history',
	archive_loaded: 'loaded older history into the brain',
	archive_nothing: 'found nothing older',
	archive_refused: 'was refused the archive',
	archive_dropped: 'dropped an archive request',
	archive_returned: "took the Archivist's finds back",
	archive_conflict: 'found older history that conflicts with a claim',
	archive_released: 'put a gap back after the Archivist',
	archive_refs_ignored: 'set aside refs no source owns'
};

/** "pm opened a follow-up": who did what, without the why. */
export function logSentence(entry: LogEntry): string {
	const who = whoName(entry.actor);
	if (entry.action === 'consulted') {
		const role = entry.why?.match(/^asked (.+)$/)?.[1];
		return role ? `${who} asked ${role} about a gap` : `${who} asked about a gap`;
	}
	return `${who} ${ACTIONS[entry.action] ?? words(entry.action)}`;
}

/** A review's trigger and stop codes, as the log's why carries them. */
const REVIEW_WORDS: Record<string, string> = {
	manual: 'on request',
	build: 'after a build',
	approval: 'after an approval',
	archive: 'after the Archivist found history',
	no_api_key: 'no API key',
	brain_unavailable: "the company's brain isn't there",
	restart: 'the server restarted'
};

/** The why of a log line, in words; null when it adds nothing to the sentence. */
export function logWhy(entry: LogEntry): string | null {
	const why = entry.why?.trim();
	if (!why) return null;
	if (entry.action === 'consulted') return null; // the sentence names who was asked
	if (entry.action === 'claim_queued') return list(why.split(/,\s*/).map(reasonWords));
	if (entry.action.startsWith('review_')) {
		const rest = why.replace(/^review:[^:\s]+:\s*/, '');
		const said = rest
			.split(/,\s*/)
			.map((part) => REVIEW_WORDS[part] ?? part)
			.filter((part) => !['done', 'stopped', 'failed', 'skipped'].includes(part));
		return said.length ? said.join(', ') : null;
	}
	return why;
}

export const NAME_MAX = 80;
export const WHY_MAX = 500;

export interface ApprovalErrors {
	by?: string;
	why?: string;
}

/** What is wrong with a typed approval before it is sent, or null when it can go. */
export function checkApproval(by: string, why: string): ApprovalErrors | null {
	const name = by.trim();
	if (!name) return { by: 'Type your name, so the log says who decided.' };
	if (name.length > NAME_MAX) return { by: `Keep your name to ${NAME_MAX} characters.` };
	if (why.trim().length > WHY_MAX) return { why: `Keep the reason to ${WHY_MAX} characters.` };
	return null;
}

export interface DecisionError {
	message: string;
	/** The field the message belongs under, for a 422. */
	field?: 'by' | 'why';
	/** The claim is no longer waiting (decided or gone): refresh the list. */
	gone?: boolean;
}

/**
 * How a failed approve or reject reads. Status wins over the server's text here: a 409 means
 * someone else decided first, whatever its detail says.
 */
export function decisionError(e: unknown): DecisionError {
	if (e instanceof ApiError) {
		// The company is building (`BUILDING` in agents/keeper/decide.py): nobody decided it.
		if (e.status === 409 && typeof e.detail === 'string' && /being rebuilt/.test(e.detail)) return { message: e.detail };
		if (e.status === 409)
			return { message: 'Someone already decided this claim. The list now shows where it stands.', gone: true };
		if (e.status === 404)
			return { message: 'This claim is gone. The list now shows the ones still waiting.', gone: true };
		if (e.status === 503)
			return {
				message:
					typeof e.detail === 'string' && e.detail
						? e.detail
						: "The company's brain isn't there. Build the company, then approve again."
			};
		if (e.status === 422 && Array.isArray(e.detail)) {
			const locs = (e.detail as FieldError[]).map((f) => f.loc.at(-1));
			if (locs.includes('why')) return { field: 'why', message: `Keep the reason to ${WHY_MAX} characters.` };
			return { field: 'by', message: `Type your name, up to ${NAME_MAX} characters.` };
		}
	}
	return { message: describeError(e) };
}

/** The kinds of accepted claim pm opens a follow-up for (`agents/roles/pm.py`). */
const FOLLOWED_UP: ClaimKind[] = ['owner', 'expert', 'decision'];

/**
 * What a lead's decision did, said once it went through, from the claim the server returned: an
 * approval re-checks the sources and projects the claim, so it can end other than accepted.
 */
export function decidedLine(
	decision: 'approve' | 'reject',
	by: string,
	claim: { statement: string; kind: ClaimKind; status: ClaimStatus }
): string {
	if (decision === 'reject') return `${by} rejected: ${claim.statement} Its gap is open again.`;
	if (claim.status === 'conflicts_with_source')
		return `${by} approved, but the sources now say otherwise, so the brain keeps what they say: ${claim.statement} pm opens a follow-up to fix the source.`;
	if (claim.status === 'stale')
		return `${by} approved, but the brain no longer has this claim's subject or evidence, so it was not added: ${claim.statement} Its gap is open again.`;
	const next = FOLLOWED_UP.includes(claim.kind) ? ' pm opens its follow-up next.' : '';
	return `${by} approved: ${claim.statement}${next}`;
}

/** A Keeper review is going among these runs. */
export function keeperRunning(runs: ActivityRun[]): boolean {
	return runs.some((r) => r.source === 'keeper' && r.status === 'running');
}

/**
 * Changes when a Keeper run appears, takes a step or changes status: the moments to read the
 * claims and the log again (a step may have queued a claim or logged a line).
 */
export function keeperRunsKey(runs: ActivityRun[]): string {
	return runs
		.filter((r) => r.source === 'keeper')
		.map((r) => `${r.id}:${r.status}:${r.steps.length}`)
		.join(' ');
}

/**
 * What Review now did, when its answer is already the end (a skipped review never reaches the
 * activity list). Null while it runs: the map shows it then.
 */
export function reviewNote(review: Review): string | null {
	const stop = review.stop ? REVIEW_WORDS[review.stop] ?? words(review.stop) : null;
	switch (review.state) {
		case 'running':
			return null;
		case 'skipped':
			return review.stop === 'no_api_key'
				? 'Review skipped: the API has no Claude key, so the Keeper only rechecked its claims and looked for new gaps.'
				: `Review skipped${stop ? `: ${stop}` : ''}.`;
		case 'done': {
			const n = review.gaps.length;
			return n ? `Review done: ${n} ${n === 1 ? 'gap' : 'gaps'} reviewed.` : 'Review done: no gap was waiting.';
		}
		case 'failed':
			return `Review failed${stop ? `: ${stop}` : ''}.`;
		case 'stopped':
			return `Review stopped${stop ? `: ${stop}` : ''}.`;
	}
}

/** A log line's time: the clock today ("14:09"), else the date ("6 Feb", with the year when not this one). */
export function logTime(iso: string, now: number = Date.now()): string {
	const t = Date.parse(iso);
	if (Number.isNaN(t)) return '';
	const at = new Date(t);
	const today = new Date(now);
	if (at.toDateString() === today.toDateString())
		return at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
	const year = at.getFullYear() === today.getFullYear() ? undefined : 'numeric';
	return at.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year });
}

/** A gap's status as a person reads it. */
const GAP_STATUS: Record<string, string> = { waiting_archive: 'Waiting for the Archivist' };

export function gapStatusWords(status: string): string {
	return GAP_STATUS[status] ?? words(status).replace(/^./, (c) => c.toUpperCase());
}

/** One piece of evidence behind a claim, named as well as the page knows it. */
export interface EvidenceRef {
	uid: string;
	/** The graph label (Person, WorkItem, ...), when known. */
	label: string | null;
	title: string;
	url: string | null;
}

/** What the map draws for a uid, if it does. */
export type Known = (uid: string) => { label: string; title: string | null; url: string | null } | null;

const PREFIX_LABELS: Record<string, string> = { person: 'Person', team: 'Team', system: 'System' };

/** Each evidence uid with its title and link from the map; people, teams and systems by their uid. */
export function evidenceRefs(uids: string[], known: Known): EvidenceRef[] {
	return uids.map((uid) => {
		const node = known(uid);
		if (node) return { uid, label: node.label, title: node.title ?? shortUid(uid), url: node.url };
		return { uid, label: PREFIX_LABELS[uid.split(':')[0]] ?? null, title: shortUid(uid), url: null };
	});
}

// --- the work behind a claim (the review page) ------------------------------------------------

const TRIGGERS: Record<Review['trigger'], string> = {
	build: 'after a build',
	manual: 'on request',
	approval: 'after an approval',
	archive: 'after the Archivist found history'
};

/** "Keeper review after a build · 17 Oct": which review wrote the claim, and when. */
export function trailHeading(review: Review, now: number = Date.now()): string {
	const at = logTime(review.started_at, now);
	return `Keeper review ${TRIGGERS[review.trigger]}${at ? ` · ${at}` : ''}`;
}

/** "3 agents, 14 graph reads": how much work the jobs took. */
export function trailSummary(trail: ClaimTrail): string {
	const agents = new Set(trail.jobs.map((j) => j.actor)).size;
	const reads = trail.jobs.reduce((n, j) => n + j.steps.length, 0);
	return `${agents} ${agents === 1 ? 'agent' : 'agents'}, ${reads} graph ${reads === 1 ? 'read' : 'reads'}`;
}

const article = (word: string) => (/^[aeiou]/i.test(word) ? 'an' : 'a');

/** What one job came to: "pm drafted an owner claim", "qa could not ground it", "Keeper wrote this claim". */
export function trailJobTitle(job: TrailJob, claim: string): string {
	const who = job.actor === 'keeper' ? 'Keeper' : job.actor;
	if (!job.wrote) return `${who} wrote nothing${job.error ? ` (${words(job.error)})` : ''}`;
	if (job.consult) {
		if (job.consult.can_ground === false) return `${who} could not ground it in the graph`;
		const kind = job.consult.kind ? CLAIM_KINDS[job.consult.kind].toLowerCase() : null;
		return kind ? `${who} drafted ${article(kind)} ${kind} claim` : `${who} drafted a claim`;
	}
	if (job.actor === 'keeper') {
		if (job.submit.claim === claim) return 'Keeper checked the drafts and wrote this claim';
		const outcome = typeof job.submit.outcome === 'string' ? words(job.submit.outcome) : 'decided';
		return `Keeper decided: ${outcome}`;
	}
	return `${who} ${words(job.tool.replace(/^submit_/, ''))}`;
}

/**
 * Why the Keeper decided as it did: the text of its decide job's `episode` log line
 * ("keeper.decide gap:x: I verified ..."), without the job prefix. Null when not logged.
 */
export function keeperReasoning(log: LogEntry[]): string | null {
	const line = [...log].reverse().find((e) => e.action === 'episode' && e.why?.startsWith('keeper.decide'));
	return line?.why?.replace(/^keeper\.decide\s+\S+:\s*/, '').trim() || null;
}

/** The gap's log lines worth listing on their own (no runner `episode` lines), oldest first. */
export function trailLog(log: LogEntry[]): LogEntry[] {
	return log.filter((e) => e.action !== 'episode');
}
