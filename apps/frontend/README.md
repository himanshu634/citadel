# frontend

The Company Brain UI: SvelteKit 2, Svelte 5 (runes), TypeScript, bits-ui primitives, Lucide
icons. It reads from the backend (`apps/backend`), never from FalkorDB directly. Until the
backend API exists, pages use sample data from the synthetic company (`src/lib/data/sample.ts`).

Design rules: [design-system.md](design-system.md). Live component gallery: `/components`.

```bash
make fe-install     # pnpm install in apps/frontend
make fe-dev         # dev server on http://localhost:5173
make fe-check       # svelte-check (types and Svelte diagnostics)
make fe-build       # static build into apps/frontend/build
```

## Layout

```
src/lib/styles/       tokens.css (every colour, size, radius) and base.css
src/lib/components/   ui/ generic, brain/ answer and graph patterns, layout/ the app frame
src/lib/data/         sample data (replace with API calls; keep the shapes in src/lib/types.ts)
src/routes/           / dashboard, /components gallery
```
