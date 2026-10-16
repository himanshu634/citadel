# AI usage

An AI coding assistant (Claude Code) was used to build this project. Parts it helped with:

- Project skeleton: uv workspace, Docker Compose, config models, CLI.
- FalkorDB connection layer and schema (index) setup, checked against the running engine.
- Ingestion: canonical models, normalize, loader and load queries, the synthetic company, the
  GitHub adapter (GraphQL fetch, git partial clone, transform) and their tests.
- Named query tools (`queries/tools/*.cypher`, `brain/tools.py`), the `brain query` CLI and the
  graph tests; the README and the docs in `docs/` (canonical-format.md is generated from the
  pydantic models).
- Frontend: design directions, the design system (tokens, components, `design-system.md`) and the
  dashboard layout in `apps/frontend`.

_Edit this file: add what you wrote yourself, what you reviewed, and what you changed._
