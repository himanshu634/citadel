// Why: TagInput's rules (what counts as a tag, which input adds one) are plain string logic, so
// they live here where vitest can test them, and the component only wires them to events.

const SEPARATORS = /[,\r\n]+/;

/** True when typed or pasted text holds more than one tag (a comma or a line break). */
export function hasSeparator(text: string): boolean {
	return SEPARATORS.test(text);
}

/**
 * The tags after adding `text`. Commas and line breaks split it, each piece is trimmed, and empty
 * pieces and tags already present (or repeated in the text) are dropped. Returns `values` itself
 * when nothing was added, so callers can tell by identity.
 */
export function addTags(values: string[], text: string): string[] {
	const next = [...values];
	for (const piece of text.split(SEPARATORS)) {
		const tag = piece.trim();
		if (tag && !next.includes(tag)) next.push(tag);
	}
	return next.length === values.length ? values : next;
}

/** The tags without `tag`; `values` itself when it was not there. */
export function removeTag(values: string[], tag: string): string[] {
	return values.includes(tag) ? values.filter((v) => v !== tag) : values;
}
