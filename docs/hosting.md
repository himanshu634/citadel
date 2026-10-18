# Hosting Citadel

A strategy for putting Company Brain on a public URL. It covers what the code requires of a
host, three ways to host it, the recommended one, and the steps to get there. Nothing here is
built yet: the repo has no Dockerfile, no CI and no production server command.

**Assumptions** (change them and the plan changes):

- The first goal is a demo URL for the hackathon judges, live today (the event ends Oct 18 2026).
- Traffic is small: a few people at a time, a handful of companies.
- The hosted companies use public data (the FalkorDB repo, the synthetic company).
- One person operates it, by hand, over SSH. No on-call.

## What the code requires of a host

These follow from how the backend works today. Each one rules options in or out.

1. **Exactly one API process, one uvicorn worker, never two at once.** Builds
   (`backend/jobs.py`) and Keeper reviews (`backend/keeper_runs.py`) run as threads inside the
   API process. At startup the API marks every build and review still `running` as `stopped`
   (`recover`). A second instance, even for a few seconds during a rolling deploy, stops the
   first one's work. This rules out serverless functions, autoscaling, replicas and
   scale-to-zero (Fly auto-stop, Cloud Run with min instances 0). A restart or deploy cuts off
   any build or review in flight, so deploy when nothing is running.
2. **One origin for the app and the API.** The frontend calls the relative path `/api`
   (`src/lib/api/client.ts`), and CORS allows only `http://localhost:5173`. So one reverse proxy
   must serve the static build and forward `/api` to uvicorn. Its SPA fallback is `200.html`,
   not `index.html`: `/c/[slug]` and `/new` are not prerendered.
3. **Long-lived event streams.** Ask, builds (`/api/events`, which never ends) and Keeper
   reviews stream Server-Sent Events. The backend pings every 15 s (`PING_SECONDS` in
   `api/deps.py`), so idle timeouts of 30 s or more are safe. The proxy must not buffer
   responses (Caddy: `flush_interval -1`; nginx: `proxy_buffering off`).
4. **A persistent disk at the repo root.** The API writes `companies/*.yaml` (companies added in
   the UI), `data/raw/` (download cache, 33 MB today), `data/jobs/`, `data/traces/` and
   `data/models/` (the embedding model, about 0.2 GB). Set `BRAIN_ROOT` to the mounted folder;
   without it the root is found by walking up to a `companies/` folder. A container without a
   volume loses every company created in the UI on restart.
5. **Memory.** FalkorDB holds about 170 MB for the current graphs. The local embedding model
   (`EMBEDDING_PROVIDER=fastembed`) adds about 1 GB to the API process while it embeds or
   answers a semantic search. Plan for 4 GB of RAM, 2 GB at the least. The low-RAM option is
   `EMBEDDING_PROVIDER=gemini`: no model in memory, but chunk text and questions go to Google.
   That is acceptable for public repos only. Changing provider means `make embed` again.
6. **No authentication, and many routes that cost money or disk.** Anyone who reaches the API
   can ask questions (spends the Anthropic key), onboard any public GitHub repo (spends the
   GitHub token and disk), edit a company's YAML, start or stop builds (a rebuild drops and reloads
   a graph), approve or reject Keeper claims, and delete chat threads. A public URL
   needs a gate in front of it (see "Access").
7. **FalkorDB stays private.** Its Redis port (6379) and Browser UI (3000) must not be public.
   Set `FALKORDB_PASSWORD`, and pin `FALKORDB_IMAGE_TAG` to the version tested locally instead
   of `latest`.
8. **Secrets come from the environment.** `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` (the `gh auth
   token` fallback does not exist on a server), `LINEAR_API_KEY` if Linear sources are hosted,
   `GEMINI_API_KEY` if Gemini embeds, MCP tokens named by `token_env`, `FALKORDB_PASSWORD`.

## Options

Prices and tier limits change; check them before choosing.

| | A. One VM, Docker Compose | B. One-machine PaaS + volume | C. App on a VM or PaaS, FalkorDB Cloud |
|---|---|---|---|
| What runs where | FalkorDB, API and Caddy on one VM | API + static files in one container (e.g. Fly.io, Railway, Render) with a volume; FalkorDB as a second service with its own volume | API as in A or B; the graphs on FalkorDB Cloud (`FALKORDB_TLS=true`) |
| Fits the one-process rule | Yes, by construction | Only with auto-stop off, one machine, and a stop-then-start deploy | Yes for the API |
| HTTPS | Caddy, automatic | The platform | As A or B |
| Data safety | Your volume snapshots | The platform's volume snapshots | Managed database backups |
| Setup today | About 2 hours | About 2 hours, more if the platform's SSE or volume rules bite | A or B plus account setup and a data copy |
| Monthly cost | Low (a 4 GB VM) | Low to medium | VM plus the Cloud tier |
| Watch out for | You patch the OS | Rolling deploys that start the new machine before the old one stops; SSE timeouts | One company uses up to 3 graphs (`brain_`, `agent_`, `keeper_`); check the tier's memory and graph limits. Latency between the API and the database region |

**Recommendation: A, one VM running Docker Compose.** It matches the code exactly: one API
process, one disk, one FalkorDB, same origin, no platform rules to fight. It is the shortest
path to a URL today and the easiest to debug over SSH. Keep C in mind for later: FalkorDB
sponsors the hackathon, the code already supports its Cloud with TLS, and it takes database
backups off your hands.

Not recommended: putting the frontend on Vercel or another static host and the API elsewhere.
It adds cross-origin requests, a CORS change and SSE through a rewrite proxy, for no gain at
this scale.

## The recommended setup

```
            internet
               │ 443 (HTTPS)
        ┌──────▼──────┐
        │    Caddy    │  static build (apps/frontend/build), SPA fallback 200.html
        └──────┬──────┘  /api/* → api:8000, no buffering
               │
        ┌──────▼──────┐
        │  API        │  uvicorn backend.api:app, 1 worker, no --reload
        │  (backend)  │  BRAIN_ROOT=/srv/citadel (volume: companies/, data/)
        └──────┬──────┘
               │ 6379 (private network only)
        ┌──────▼──────┐
        │  FalkorDB   │  pinned tag, requirepass, volume falkordb_data
        └─────────────┘
```

Pieces to add to the repo:

- **`Dockerfile`** (multi-stage). Stage 1: Node + pnpm, `pnpm install --frozen-lockfile` and
  `pnpm build` in `apps/frontend`. Stage 2: Python 3.12 + uv, `uv sync --frozen --no-dev`,
  copy the apps and `companies/`. Command:
  `uvicorn backend.api:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers`.
  Run as a non-root user.
- **`docker-compose.prod.yml`**: services `falkordb` (no published ports), `api` (env file,
  volume at `BRAIN_ROOT`, `restart: unless-stopped`, depends on FalkorDB healthy) and `caddy`
  (ports 80 and 443, the built frontend, a volume for its certificates). The existing
  `docker-compose.yml` stays the local one.
- **`Caddyfile`**: the site, `basic_auth` (see "Access"), `handle /api/*` with
  `reverse_proxy api:8000 { flush_interval -1 }`, and a file server with
  `try_files {path} {path}.html /200.html`.
- **A first-run step** that seeds the volume: copy the repo's `companies/*.yaml` into it when
  it is empty, and download the embedding model once (`make embed` on the server does it).

## Access

Pick one before the URL goes out:

1. **Shared password at the proxy (recommended for today).** Caddy `basic_auth` on the whole
   site. Give the judges the username and password with the submission. No code change.
2. **An identity gate** (Cloudflare Access or similar) in front of the VM: sign-in by email,
   no password to share. Check that it does not cut the 15 s-pinged event streams.
3. **Open read, gated writes** (a later code change): an env flag that refuses onboarding,
   YAML edits, builds and claim decisions without an admin token, so Ask and browsing stay
   open. Ask still spends the Anthropic key, so it needs a rate limit too.

With any of them, set a monthly spend limit on the Anthropic key in the Anthropic Console, and
consider `ANTHROPIC_MODEL=claude-haiku-5-5` for the demo to cut cost per question.

## Getting the data there

| Graph | Rebuild on the server? | How to move it |
|---|---|---|
| `brain_<slug>` | Yes: from `data/raw/` with `make ingest` (no API calls), then it embeds | Copy `data/raw/<slug>/` and rebuild, or copy the database file |
| `agent_<slug>` (chat history, checkpoints) | No | Copy the database file |
| `keeper_<slug>` (gaps, claims, log) | No | Copy the database file |
| `brain_test_*` | Not needed | Delete before copying |

Simplest path: on the laptop, delete the `brain_test_*` graphs, run `redis-cli BGSAVE` in the
FalkorDB container, copy `dump.rdb` from its data folder into the server's FalkorDB volume
before the first start, and copy `data/traces/` and `data/jobs/` with the rest of the volume.
The server then starts with the same graphs, Keeper ledger and chat history as the laptop, and
nothing has to embed. Use the same FalkorDB version on both sides.

## Steps for today

1. Create a 4 GB VM (Ubuntu LTS) in a region near the judges. Open only 22, 80 and 443.
2. Point a DNS name at it (any subdomain you own).
3. Add the Dockerfile, the prod compose file and the Caddyfile on a branch; build and run them
   locally once against a copy of the data.
4. On the VM: install Docker, clone the repo, write `.env` with the secrets and
   `FALKORDB_PASSWORD`, copy the seeded volume and `dump.rdb`, then
   `docker compose -f docker-compose.prod.yml up -d --build`.
5. Check: the app loads over HTTPS behind the password; `/c/falkordb` reloads without a 404;
   one Ask question streams to the end; the Systems page shows the Keeper log; a build of
   `synthetic` streams its progress; FalkorDB's port does not answer from outside.
6. Send the URL and password with the submission.

**Rollback:** the previous image stays on the VM. `docker compose ... up -d` with the previous
tag puts it back; the volumes are untouched. Before any risky change, snapshot the VM disk.

## Later

- **Backups:** a nightly `BGSAVE` copied off the VM (object storage), plus the `BRAIN_ROOT`
  folder. Or move to FalkorDB Cloud (option C).
- **Deploys:** a GitHub Action that runs `make lint test` and builds the image on every PR, and
  on `main` pushes it to a registry. Deploying stays one command on the VM, run when no build or
  review is active (`/api/events` shows builds; the Systems page shows reviews).
- **Monitoring:** an uptime check on the site; Docker log rotation; `make traces` on the server
  for Ask health. Disk use under `data/raw/` grows with each onboarded repo.
- **Scaling past one process** needs a code change first: builds and reviews would have to move
  to a worker with a shared queue and a heartbeat, and `recover` would have to tell a dead
  process from a live one. Not needed at demo scale.

## Decisions for you

| Decision | Default in this plan |
|---|---|
| Where to host | One VM with Docker Compose (option A) |
| Who may use it | Shared password at the proxy |
| Embeddings on the server | Local model, 4 GB VM; Gemini if the VM must be 2 GB |
| Which data goes up | Copy the laptop's FalkorDB file (graphs, Keeper ledger, chats) without the test graphs |
| Model for the demo | Keep Sonnet; switch to Haiku if the spend limit is tight |
| Domain | A subdomain you already own |
