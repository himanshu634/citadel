/**
 * Which Claude model the next Ask question runs on (design direction P, "Chip in the composer").
 *
 * Why: the server offers a fixed list (GET /api/models: Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.1)
 * and a default (Haiku 5.5). The pick is per question, so a follow-up may use another model; it is
 * remembered in this browser, so the next visit starts where you left off. A remembered id the
 * server no longer offers falls back to the default. Until the list arrives (or when it fails)
 * nothing is picked and questions run on the server's default.
 */
import { api } from './api/client';
import type { ModelInfo } from './types';

export const MODEL_KEY = 'citadel.ask.model';

function remembered(): string | null {
	try {
		return localStorage.getItem(MODEL_KEY);
	} catch {
		return null; // storage blocked (private window, a preview): nothing remembered
	}
}

export class ModelChoice {
	models = $state<ModelInfo[]>([]);
	defaultId = $state<string | null>(null);
	/** The picked model's id; null until the list arrives. */
	selected = $state<string | null>(null);

	/** The picked model, or null while the list is loading (or failed). */
	get current(): ModelInfo | null {
		return this.models.find((m) => m.id === this.selected) ?? null;
	}

	async load(): Promise<void> {
		try {
			const out = await api.models();
			this.models = out.models;
			this.defaultId = out.default;
			const saved = remembered();
			const known = (id: string | null) => !!id && out.models.some((m) => m.id === id);
			this.selected = known(saved) ? saved : known(out.default) ? out.default : (out.models[0]?.id ?? null);
		} catch {
			// The picker stays hidden and questions run on the server's default.
		}
	}

	pick(id: string): void {
		if (!this.models.some((m) => m.id === id)) return;
		this.selected = id;
		try {
			localStorage.setItem(MODEL_KEY, id);
		} catch {
			// Not remembered; the pick still holds on this page.
		}
	}

	/** A model's short name ("Opus 5.5") from its id; the id itself when it is not in the list. */
	nameOf(id: string | null | undefined): string | null {
		if (!id) return null;
		return this.models.find((m) => m.id === id)?.name ?? id;
	}
}
