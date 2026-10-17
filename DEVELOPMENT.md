# Development

How to get Company Brain running on your machine, from a fresh clone to asking the brain a
question in the app. Every step goes through the Makefile; `make help` lists all targets.

## 1. Install the prerequisites

| Tool | Version | Used for |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) (Desktop or Engine with Compose v2) | any recent | FalkorDB |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | latest | Python 3.12 and the backend packages (uv installs Python for you) |
| [Node.js](https://nodejs.org/) | 22 LTS | the frontend |
| [pnpm](https://pnpm.io/installation) | 9 or newer | frontend packages |
| `make`, `git` | | everything |
| [GitHub CLI](https://cli.github.com/) `gh` (optional) | | a GitHub token without editing `.env` |

On macOS with Homebrew:

```bash
brew install uv node pnpm gh
```

## 2. Clone and set up

```bash
git clone https://github.com/himanshu634/citadel.git
cd citadel
make setup
```

`make setup` runs `uv sync` (creates `.venv` with Python 3.12 and every backend package) and
copies `.env.example` to `.env` if you don't have one yet.

## 3. Fill in `.env`

Everything works with the defaults except the keys below. Each is only needed for the feature
next to it.

| Variable | Needed for | Where to get it |
|---|---|---|
| `GITHUB_TOKEN` | building a brain from a GitHub repo (`make sync`, the **+** in the app) | a read-only [personal access token](https://github.com/settings/tokens); leave empty to fall back to `gh auth token` |
| `ANTHROPIC_API_KEY` | asking questions (`make ask`, the Ask page, `make eval`) and the Keeper's review jobs (without it a review only re-projects and notices) | [console.anthropic.com](https://console.anthropic.com/) |
| `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT` | choosing the answering model | defaults: `claude-haiku-5-5`, `medium` |
| `KEEPER_BUDGET`, `KEEPER_BUILD_BUDGET`, `KEEPER_NOTICE_CAP` | tuning the Keeper: gaps per on-demand review, gaps per review after a build, new gaps per noticing run | defaults: 5, 3, 10 |
| `LINEAR_API_KEY` | `linear` sources and `make linear-seed` | Linear → Settings → Security & access |
| `FALKORDB_*` | a different port, a password, or FalkorDB Cloud | see [Using FalkorDB Cloud](#using-falkordb-cloud) |

The synthetic demo company needs none of them.

## 4. Start FalkorDB

```bash
make up
```

This starts the `falkordb/falkordb` container and waits until it is healthy:

- Graph database (Redis protocol) on `localhost:6379`
- FalkorDB Browser UI on <http://localhost:3000> (`make browser` opens it)

Graphs live in a named Docker volume, so `make down` keeps them. `make logs` follows the
container log, `make ps` shows its status.

## 5. Build your first brain

### Offline, no keys: the synthetic company

```bash
make synthetic
make stats SLUG=synthetic
make query SLUG=synthetic TOOL=owners_vs_experts
make query SLUG=synthetic TOOL=path_between P="from_uid=person:erin to_uid=system:Auth"
```

`make synthetic` regenerates the demo data (6 people, 2 teams, 4 systems, 15 work items),
creates the indexes and loads it into the graph `brain_synthetic`. `make tools` lists every
named tool with its parameters; add `JSON=1` to any `make query` for raw rows.

### A real repo: FalkorDB itself (needs a GitHub token)

```bash
make schema       # indexes on brain_falkordb (SLUG defaults to falkordb)
make sync         # fetch + ingest; about 3 minutes the first time
make query TOOL=experts_for_system P="system=CI"
```

Raw API responses are cached under `data/raw/`, so `make ingest` re-runs without calling
GitHub. `FULL=1` ignores the incremental cursors, `SOURCE=github` limits a run to one source.
To add your own company, see [docs/adding-a-company.md](docs/adding-a-company.md).

## 6. Ask the brain

Needs `ANTHROPIC_API_KEY`.

```bash
make ask SLUG=synthetic Q="Who should review a change to Billing, and why?"
make chat SLUG=synthetic                 # multi-turn conversation on one thread
make chat SLUG=synthetic OFFLINE=1       # one scripted turn, no key: checks the wiring
```

## 7. Run the app

```bash
make fe-install   # first time only: pnpm install in apps/frontend
make dev          # API on http://127.0.0.1:8000 and the app on http://localhost:5173
```

Open <http://localhost:5173>. The app talks to the API through `/api` (Vite proxies it to
port 8000), never to FalkorDB directly. Pick a company on the left rail, then use the Overview,
Graph, Ask and Build pages. The **+** on the rail adds a company from any public GitHub repo.

To run the two halves in separate terminals, use `make api` and `make fe-dev`. To move the
API, run `make dev API_PORT=9000`; the proxy follows it.

Quick check that the API is up:

```bash
curl http://127.0.0.1:8000/api/companies
```

## 8. Try the Keeper

The Keeper reviews what the brain could not answer and updates it
([docs/agents.md](docs/agents.md#the-keeper)). Its records live in the graph
`keeper_synthetic`. It runs its jobs on Claude, so set `ANTHROPIC_API_KEY` first (without one a
review only re-projects claims and notices gaps, and is recorded as skipped). With the synthetic
company built and `make dev` running, open its Systems page and click **Review now**.

The review shows step by step on the page's agent trail. It notices gaps on its own (here a
system whose declared owner is not the person doing most of its work), consults `pm` and `qa`,
and lets the Keeper decide. A claim that touches a high-impact system is critical, so it waits
for your approval in the rail: type your name, optionally say why, and approve or reject. The
rail's log says who did what, and why. Failed questions and thumbs-down answers on the Ask page
become gaps too, and the app runs a review after every build. While a company builds, Review now,
approve and reject are refused (a rebuild's brain is empty until its ingest ends); try again when
the build finishes. The same actions are in the API under `/api/companies/<slug>/keeper/`.

## 9. The agent simulation (optional)

The original simulated company, no longer the product story:

```bash
make agents                                           # the roles, their jobs and read tools
make sim SLUG=synthetic SCENARIO=sprint OFFLINE=1     # a full sprint with scripted policies
```

`OFFLINE=1` plays each role with a deterministic policy, so no API key is used. Scenarios:
`sprint`, `race`, `regression`. The spec is in [docs/agents.md](docs/agents.md).

## Tests and checks

```bash
make test         # pytest; graph tests need `make up`, otherwise they are skipped
make test ARGS="-k normalize"   # only the tests whose name matches
make lint         # ruff check + format check
make fmt          # ruff format + autofix
make fe-check     # svelte-check
make fe-test      # vitest
make eval         # agent evals on brain_synthetic; calls the API, so not part of make test
```

Graph tests create throwaway graphs and delete them afterwards, so they don't touch your
company brains.

## Using FalkorDB Cloud

The same code runs against a cloud instance. In `.env`, set `FALKORDB_HOST`, `FALKORDB_PORT`,
`FALKORDB_USERNAME` and `FALKORDB_PASSWORD` from the console, and `FALKORDB_TLS=true` if the
instance uses TLS. Skip `make up`; everything else is the same.

## Troubleshooting

| Problem | Fix |
|---|---|
| `make up` fails: port 6379 or 3000 is already in use | Another Redis or app holds it. Set `FALKORDB_PORT` / `FALKORDB_BROWSER_PORT` in `.env` and run `make up` again |
| Graph tests are skipped | FalkorDB is not running: `make up` |
| `make sync` says the repo is private | Private repos are refused unless the company config says `data_permission: own` |
| GitHub rate limit or 401 | Set `GITHUB_TOKEN`, or run `gh auth login` |
| Ask returns an auth error | `ANTHROPIC_API_KEY` is missing or wrong in `.env`; restart `make dev` after changing it |
| The app loads but shows no companies or errors | `make api` is not running, or it is on another port: start it with the same `API_PORT` |
| Vector index dimension warning | `EMBEDDING_DIM` changed after the index was created: `make reset SLUG=<slug> CONFIRM=1`, then rebuild |
| Start a company over | `make reset SLUG=<slug> CONFIRM=1` deletes its graphs (`brain_`, `agent_`, `keeper_`), build history and traces; the config and raw cache are kept |
| A Keeper review is recorded as skipped | `ANTHROPIC_API_KEY` is missing: set it and restart `make dev` |
| Wipe all local graphs | `docker compose down -v` deletes the FalkorDB volume |
