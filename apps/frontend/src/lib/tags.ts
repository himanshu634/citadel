// Why: TagInput's rules (what counts as a tag, which input adds one) are plain string logic, so
// they live here where vitest can test them, and the component only wires them to events.

/**
 * The pieces of `text` between separators. A line break always separates; a comma separates only
 * outside `{}`, so a brace glob such as `**\/*.{ts,tsx}` stays one tag. Pieces are not trimmed
 * and may be empty.
 */
function pieces(text: string): string[] {
	const out: string[] = [];
	let depth = 0;
	let start = 0;
	for (let i = 0; i < text.length; i++) {
		const c = text[i];
		if (c === '{') depth++;
		else if (c === '}') depth = Math.max(0, depth - 1);
		else if (c === '\n' || c === '\r' || (c === ',' && depth === 0)) {
			out.push(text.slice(start, i));
			start = i + 1;
		}
		if (c === '\n' || c === '\r') depth = 0;
	}
	out.push(text.slice(start));
	return out;
}

/** True when `text` ends inside an unclosed `{`: a comma typed now belongs to the glob. */
export function inOpenBrace(text: string): boolean {
	let depth = 0;
	for (const c of text) {
		if (c === '{') depth++;
		else if (c === '}') depth = Math.max(0, depth - 1);
		else if (c === '\n' || c === '\r') depth = 0;
	}
	return depth > 0;
}

/** True when typed or pasted text holds more than one tag (a comma outside braces, or a line break). */
export function hasSeparator(text: string): boolean {
	return pieces(text).length > 1;
}

/**
 * The tags after adding `text`. Commas outside `{}` and line breaks split it, each piece is
 * trimmed, and empty pieces and tags already present (or repeated in the text) are dropped.
 * Returns `values` itself when nothing was added, so callers can tell by identity.
 */
export function addTags(values: string[], text: string): string[] {
	const next = [...values];
	for (const piece of pieces(text)) {
		const tag = piece.trim();
		if (tag && !next.includes(tag)) next.push(tag);
	}
	return next.length === values.length ? values : next;
}

/** The tags without `tag`; `values` itself when it was not there. */
export function removeTag(values: string[], tag: string): string[] {
	return values.includes(tag) ? values.filter((v) => v !== tag) : values;
}
