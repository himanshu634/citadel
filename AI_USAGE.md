# AI usage

I used Claude Code to write the code: the Python packages, the Cypher queries, the tests, the
Svelte app and most of the docs. The design is mine. I decided the architecture and the rules
the agents follow, and I picked every screen from mockups before any of it was built. Every
change went in as a PR that I reviewed and merged.

## Trade-offs where I took AI's help

For these, Claude laid out the options and what each would cost. I made the call.

- **Embeddings.** A local model (no API key, about 1 GB of RAM in the API) or a hosted API. I
  went local with `BAAI/bge-base-en-v1.5` and later added Gemini as an option (#34, #37).
- **Graph rendering.** A WebGL library (sigma.js, cytoscape) or plain Canvas 2D with d3-force.
  Canvas handles the few thousand nodes we draw, with fewer dependencies (#17).
- **Linear.** Let the agent call Linear live over MCP, or ingest tickets through an adapter. I
  chose the adapter: a live call gives no graph path and nothing stable to cite (#18).
- **Keeper restarts.** A heartbeat on every running review, or one process per FalkorDB that
  stops leftover reviews when it starts. The heartbeat was built and then dropped (#38, #47).
- **Database users.** A FalkorDB user per agent role, or one shared connection. For the demo the
  agents share one connection. The permission table is checked in code, and its `ACL SETUSER`
  lines are rendered but not applied (`apps/agents/agents/acl.py`).
- **Default model.** Haiku 5.5 for speed and cost, with a picker per question for the larger
  models (#9, #25).

## What I checked

On 2026-10-17, against FalkorDB in local Docker:

- `make test`: 869 passed, 0 skipped. That includes the graph tests and one live question to
  Claude (`apps/agents/tests/test_agent_live.py`).
- `make fe-test`: 481 passed in 27 files. `make fe-check` and `make lint` are clean.
- `brain_falkordb` is built from the public FalkorDB/FalkorDB repo: 18,424 nodes and 7,716
  embedded chunks. A live Keeper review left one `Claim` in it.
- The agent evals run real Claude questions through deterministic checks: see
  [Evals](docs/evals.md).

## What I have not checked

- The MCP connector against a real MCP server.
- Linear against a real workspace (`make linear-seed`). It is tested on a hand-written cache only.
- FalkorDB Cloud. The TLS setting is there, but I only ran on Docker.
- Opus 5.5 and Fable 5.1 from the model picker. Haiku and Sonnet were run live.
