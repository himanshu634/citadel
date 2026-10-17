# frontend

The Company Brain UI: SvelteKit 2, Svelte 5 (runes), TypeScript, bits-ui primitives, Lucide
icons. It reads from the backend API (`apps/backend`, `make api`; vite proxies `/api`), never from
FalkorDB directly.

Design rules: [design-system.md](design-system.md). Live component gallery: `/components`.

```bash
make fe-install     # pnpm install in apps/frontend
make fe-dev         # dev server on http://localhost:5173
make fe-check       # svelte-check (types and Svelte diagnostics)
make fe-test        # vitest unit tests
make fe-build       # static build into apps/frontend/build
```

## Layout

```
src/lib/styles/       tokens.css (every colour, size, radius) and base.css
src/lib/components/   ui/ generic, brain/ answer and graph patterns, layout/ the app frame
src/lib/types.ts      API shapes, written by hand to match the backend models
src/routes/           / (opens the last-used company, or the first-run state)
                      /c/[slug] overview, /c/[slug]/{ask,graph,systems,build,settings}
                      /new (add a company), /components gallery
src/routes/components/*-samples.ts   sample data for the gallery only
```
