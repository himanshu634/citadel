# Company Brain: one entry point for day-to-day commands.
# Each target wraps `uv run brain ...` or `docker compose ...`, so you never type uv directly.
# Most targets act on one company: pass SLUG=<slug> (default: falkordb).
#
#   make help                      list targets
#   make schema SLUG=synthetic     run a target for another company

SLUG ?= falkordb
BRAIN := uv run brain

.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps browser init schema fetch ingest sync stats query tools ask reset brain test lint fmt check clean synthetic fe-install fe-dev fe-check fe-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Variables: SLUG=$(SLUG)  TOOL=<name>  P="k=v ..."  JSON=1  SOURCE=<type>  FULL=1  NAME=<display name>  CONFIRM=1  ARGS=\"...\""

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

browser: ## Open the FalkorDB Browser UI
	open http://localhost:3000

# --- Company graph ----------------------------------------------------------------------------

init: ## Write companies/$(SLUG).yaml template (NAME="Display Name" optional)
	$(BRAIN) init $(SLUG) $(if $(NAME),--name "$(NAME)")

schema: ## Create indexes on graph brain_$(SLUG) (safe to re-run)
	$(BRAIN) schema $(SLUG)

fetch: ## Pull raw data for $(SLUG) into data/raw/ (SOURCE=github to limit)
	$(BRAIN) fetch $(SLUG) $(if $(SOURCE),--source $(SOURCE))

ingest: ## Load cached data into brain_$(SLUG) (FULL=1 ignores sync cursors)
	$(BRAIN) ingest $(SLUG) $(if $(filter 1 yes,$(FULL)),--full) $(if $(SOURCE),--source $(SOURCE))

sync: ## fetch + ingest for $(SLUG)
	$(BRAIN) sync $(SLUG) $(if $(filter 1 yes,$(FULL)),--full) $(if $(SOURCE),--source $(SOURCE))

stats: ## Node and relationship counts for brain_$(SLUG)
	$(BRAIN) stats $(SLUG)

ask: ## Ask brain_$(SLUG) a question: make ask SLUG=synthetic Q="who knows Auth?" (THREAD=id follows up)
	$(BRAIN) ask $(SLUG) "$(Q)" $(if $(THREAD),--thread $(THREAD))

synthetic: ## Regenerate the synthetic company JSONL and load it into brain_synthetic
	uv run python apps/backend/examples/synthetic_company/generate.py
	$(BRAIN) schema synthetic
	$(BRAIN) ingest synthetic --full

query: ## Run a named tool: make query TOOL=experts_for_system P="system=CI" (JSON=1 for JSON)
	$(BRAIN) query $(SLUG) $(TOOL) $(P) $(if $(filter 1 yes,$(JSON)),--json)

tools: ## List the named query tools and their parameters
	$(BRAIN) tools

reset: ## Delete graph brain_$(SLUG); needs CONFIRM=1
	$(BRAIN) reset $(SLUG) $(if $(filter 1 yes,$(CONFIRM)),--yes)

brain: ## Run any brain command: make brain ARGS="query falkordb graph_stats"
	$(BRAIN) $(ARGS)

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

# --- Quality ----------------------------------------------------------------------------------

test: ## Run pytest (needs FalkorDB up for graph tests)
	uv run pytest apps/backend/tests $(ARGS)

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
