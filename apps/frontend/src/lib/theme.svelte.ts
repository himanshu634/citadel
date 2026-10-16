/**
 * Theme preference: 'system' follows the OS, 'light'/'dark' pin it via <html data-theme>.
 * app.html applies the stored value before first paint, so there is no flash.
 */
import { createContext } from 'svelte';

export type ThemePreference = 'system' | 'light' | 'dark';
const KEY = 'citadel-theme';

export class Theme {
	preference = $state<ThemePreference>('system');

	constructor() {
		try {
			const stored = localStorage.getItem(KEY);
			if (stored === 'light' || stored === 'dark') this.preference = stored;
		} catch {
			// storage blocked: stay on 'system'
		}
	}

	set(next: ThemePreference) {
		this.preference = next;
		const root = document.documentElement;
		if (next === 'system') root.removeAttribute('data-theme');
		else root.dataset.theme = next;
		try {
			if (next === 'system') localStorage.removeItem(KEY);
			else localStorage.setItem(KEY, next);
		} catch {
			// storage blocked: the choice lasts for this page only
		}
	}
}

export const [getTheme, setTheme] = createContext<Theme>();
