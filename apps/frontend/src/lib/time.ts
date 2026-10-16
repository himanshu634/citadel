/**
 * Short relative times for lists ("just now", "5 min ago", "3 h ago", "2 d ago", then a date).
 */
export function ago(iso: string, now: number = Date.now()): string {
	const then = Date.parse(iso);
	if (Number.isNaN(then)) return '';
	const s = Math.max(0, Math.round((now - then) / 1000));
	if (s < 60) return 'just now';
	const m = Math.round(s / 60);
	if (m < 60) return `${m} min ago`;
	const h = Math.round(m / 60);
	if (h < 24) return `${h} h ago`;
	const d = Math.round(h / 24);
	if (d < 7) return `${d} d ago`;
	return new Date(then).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}
