# Company Brain: one entry point for day-to-day commands.
# Each target wraps `uv run brain ...`, `uv run agents ...`, `uv run backend ...` or
# `docker compose ...`, so you never type uv directly.
# Most targets act on one company: pass SLUG=<slug> (default: falkordb).
#
#   make help                      list targets
#   make schema SLUG=synthetic     run a target for another company

SLUG ?= falkordb
API_PORT ?= 8000
BRAIN := uv run brain
AGENTS := uv run agents
BACKEND := uv run backend

.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps browser init schema fetch ingest embed sync stats query tools ask chat eval eval-drafts traces reset linear-seed brain test lint fmt check clean synthetic api dev fe-install fe-dev fe-check fe-build fe-test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Variables: SLUG=$(SLUG)  TOOL=<name>  P="k=v ..."  JSON=1  SOURCE=<type>  FULL=1  NAME=<display name>  CONFIRM=1  ARGS=\"...\"  API_PORT=$(API_PORT)"

# --- Environment ------------------------------------------------------------------------------

setup: ## Install deps (uv sync) and create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
	uv sync

up: ## Start FalkorDB (Docker) and wait until healthy
	docker compose up -d --wait

down: ## Stop FalkorDB (data is kept in the named volume)
	docker compose down

logs: ## Follow FalkorDB logs
	docker compose logs -f falkordb

ps: ## Show container status
	docker compose ps

browser: ## Open the FalkorDB Browser UI (FALKORDB_BROWSER_PORT in .env, default 3000)
	open http://localhost:$$(sed -n 's/^FALKORDB_BROWSER_PORT=\(.\{1,\}\)/\1/p' .env 2>/dev/null | grep . || echo 3000)

# --- Company graph ----------------------------------------------------------------------------

init: ## Write companies/$(SLUG).yaml template (NAME="Display Name" optional)
	$(BRAIN) init $(SLUG) $(if $(NAME),--name "$(NAME)")

schema: ## Create indexes on graph brain_$(SLUG) (safe to re-run)
	$(BRAIN) schema $(SLUG)

fetch: ## Pull raw data for $(SLUG) into data/raw/ (SOURCE=github to limit)
	$(BRAIN) fetch $(SLUG) $(if $(SOURCE),--source $(SOURCE))

ingest: ## Load cached data into brain_$(SLUG), then embed (FULL=1 ignores sync cursors)
	$(BRAIN) ingest $(SLUG) $(if $(filter 1 yes,$(FULL)),--full) $(if $(SOURCE),--source $(SOURCE))

embed: ## Embed new or changed chunk text in brain_$(SLUG) (ALL=1 re-embeds every chunk)
	$(BRAIN) embed $(SLUG) $(if $(filter 1 yes,$(ALL)),--all)

sync: ## fetch + ingest for $(SLUG)
	$(BRAIN) sync $(SLUG) $(if $(filter 1 yes,$(FULL)),--full) $(if $(SOURCE),--source $(SOURCE))

stats: ## Node and relationship counts for brain_$(SLUG)
	$(BRAIN) stats $(SLUG)

ask: ## Ask brain_$(SLUG) a question: make ask SLUG=synthetic Q="who knows Auth?" (THREAD=id follows up)
	$(AGENTS) ask $(SLUG) "$(Q)" $(if $(THREAD),--thread $(THREAD))

chat: ## Chat with brain_$(SLUG) (OFFLINE=1: one scripted turn, no API key; THREAD=id resumes)
	$(AGENTS) chat $(SLUG) $(if $(filter 1 yes,$(OFFLINE)),--offline) $(if $(THREAD),--thread $(THREAD))

synthetic: ## Regenerate the synthetic company JSONL, load and embed it into brain_synthetic
	uv run python apps/brain/examples/synthetic_company/generate.py
	$(BRAIN) schema synthetic
	$(BRAIN) ingest synthetic --full

query: ## Run a named tool: make query TOOL=experts_for_system P="system=CI" (JSON=1 for JSON)
	$(BRAIN) query $(SLUG) $(TOOL) $(P) $(if $(filter 1 yes,$(JSON)),--json)

tools: ## List the named query tools and their parameters
	$(BRAIN) tools

agents: ## List the agent roles, their jobs and read tools
	$(AGENTS) agents

# Evals default to the synthetic company; SLUG=falkordb runs the live repo's cases.
EVAL_SLUG = $(if $(filter file,$(origin SLUG)),synthetic,$(SLUG))

eval: ## Agent evals (calls the API; SLUG defaults to synthetic): CASE=id|tag REPEAT=3 MODEL=.. EFFORT=.. BASELINE=file
	uv run python -m agents.evals --slug $(EVAL_SLUG) $(foreach c,$(CASE),--case $(c)) \
		$(if $(REPEAT),--repeat $(REPEAT)) $(if $(MODEL),--model $(MODEL)) \
		$(if $(EFFORT),--effort $(EFFORT)) $(if $(BASELINE),--baseline $(abspath $(BASELINE)))

chats-backfill: ## Chat history for $(SLUG)'s threads asked before it existed (from checkpoints + traces); ALL=1 adds untraced ones
	$(AGENTS) chats-backfill $(SLUG) $(if $(ALL),--all)

traces: ## How the brain did on live questions (CLI + Ask page) for $(SLUG): rates, p50/p95; DAYS=7
	$(AGENTS) traces $(SLUG) $(if $(DAYS),--days $(DAYS))

eval-drafts: ## Thumbs-down answers of $(SLUG) as draft eval cases (printed; WRITE=1 appends to the case file) DAYS=..
	uv run python -m agents.evals.drafts --slug $(SLUG) $(if $(DAYS),--days $(DAYS)) \
		$(if $(filter 1 yes,$(WRITE)),--write)

reset: ## Delete graphs brain_/agent_/keeper_$(SLUG), its build history and Ask traces; needs CONFIRM=1
	$(BACKEND) reset $(SLUG) $(if $(filter 1 yes,$(CONFIRM)),--yes)

linear-seed: ## Fill the Linear workspace of $(SLUG) with the synthetic tickets (CONFIRM=1)
	$(BRAIN) linear-seed $(SLUG) $(if $(filter 1 yes,$(CONFIRM)),--yes)

brain: ## Run any brain command: make brain ARGS="query falkordb graph_stats"
	$(BRAIN) $(ARGS)

# --- API ---------------------------------------------------------------------------------------

api: ## API on http://127.0.0.1:$(API_PORT) (auto-reload)
	uv run uvicorn backend.api:app --host 127.0.0.1 --port $(API_PORT) --reload

dev: ## API + frontend dev server together
	$(MAKE) -j2 api fe-dev

# --- Frontend (apps/frontend, pnpm) ------------------------------------------------------------

FE := pnpm --dir apps/frontend

fe-install: ## Install frontend deps
	$(FE) install

fe-dev: ## Frontend dev server on http://localhost:5173
	$(FE) dev --port 5173

fe-check: ## Type-check the frontend (svelte-check)
	$(FE) check

fe-build: ## Static frontend build into apps/frontend/build
	$(FE) build

fe-test: ## Frontend unit tests (vitest)
	$(FE) test

# --- Quality ----------------------------------------------------------------------------------

test: ## Run pytest (needs FalkorDB up for graph tests)
	uv run pytest $(ARGS)

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Ruff format + autofix
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Lint and test

clean: ## Remove caches (keeps data/ and the FalkorDB volume)
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) \
		-not -path "./.venv/*" -prune -exec rm -rf {} +
