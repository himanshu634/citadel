# Adding a company

A company is one YAML file, `companies/<slug>.yaml`, and becomes one graph, `brain_<slug>`.
Nothing in the loader, the schema or the queries knows about a particular company or tool.
There are a few ways in.

Every config declares `data_permission`:

| value | meaning |
|---|---|
| `public` | public repos and published material only |
| `synthetic` | made-up demo data |
| `own` | data you own; the only value that allows a private GitHub repo (ingestion refuses one otherwise) |

## (a) A public GitHub repo

```bash
make init SLUG=acme NAME="Acme"      # writes companies/acme.yaml (commented template)
```

Edit the template:

```yaml
slug: acme
name: "Acme"
data_permission: public
window:
  since: 2026-04-15                   # ingest activity on/after this date
sources:
  - type: github
    repo: acme/engine
    include: [commits, pull_requests, issues, reviews, codeowners, repo_docs]
systems:
  rules:                              # first match wins; glob on the repo-relative path
    - { match: "src/storage/**", system: "Storage" }
    - { match: ".github/workflows/**", system: "CI" }
  fallback: depth_2                   # other files: first two folders, e.g. "src/api"
  ignore: ["vendor/**", "**/*.lock"]
people:
  bots: ["renovate"]                  # logins ending in [bot] are bots automatically
  aliases: {}                         # "git author name" -> "login" when GitHub can't link them
```

Then:

```bash
make schema SLUG=acme
make sync SLUG=acme                   # fetch (network, cached under data/raw/) + ingest
make query SLUG=acme TOOL=list_systems
```

A GitHub token is needed: `GITHUB_TOKEN` in `.env`, or a logged-in `gh` CLI. The first fetch of
a busy repo takes a few minutes; later syncs only pull what changed. To tune `systems.rules`,
look at `make query SLUG=acme TOOL=list_systems`, edit the rules, and run
`make ingest SLUG=acme FULL=1` (no network needed: the transform reads the cache).

Several repos? Add several `- type: github` entries; they land in the same company graph.

## (b) Other tools: Slack, Jira, Linear, a wiki

Two options.

**Convert to canonical JSONL.** Write the export as the files described in
[canonical-format.md](canonical-format.md) (people, work_items, changes, documents, links ...),
put them in a folder and add:

```yaml
sources:
  - type: canonical_jsonl
    path: data/inbox/acme/jsonl
```

Slack threads become `WorkItem`s with `kind: thread`, Jira issues `kind: ticket`. Every line is
validated; a bad one stops ingestion with its file and line number.

**Plain documents.** A folder of markdown / text files (design docs, ADRs, runbooks):

```yaml
sources:
  - type: local_docs
    path: data/inbox/acme/docs
```

**Write an adapter.** For a source you want to sync repeatedly, copy
[`apps/backend/brain/adapters/_template.py`](../apps/backend/brain/adapters/_template.py) to
`adapters/<name>.py`. An adapter is two methods and its config model:

- `fetch(company, source, cache_dir)`: all network I/O; writes raw responses under
  `data/raw/<slug>/<name>/` (resumable, cached).
- `records(company, source, cache_dir)`: a pure transform from that cache to
  `brain.canonical` records. No network, so re-ingesting costs no API calls and tests can use
  recorded fixtures (see `tests/fixtures/github/`).
- A `SourceConfig` subclass with `type: Literal["<name>"]` and its settings; the company YAML
  is validated against it.

Then register it with one line in `apps/backend/brain/adapters/__init__.py`. That is the only
change outside the new file.

Rules for adapters: never emit email addresses (identify people by login or handle), raise
`SourceUnavailable` when there is nothing to read yet, and enforce `data_permission` if the
source can tell public from private data.

## (d) Linear

Tickets, their assignees and blockers, and the pull requests attached to them. Linear data is
private, so ingestion refuses unless the config says `data_permission: own` (your own workspace)
or `synthetic`.

```yaml
data_permission: own
sources:
  - type: linear
    workspace: acme              # the URL key: linear.app/acme
    teams: [ENG, OPS]            # team keys; empty means every team the key can see
people:
  aliases: { "Sam P.": "sam" }   # Linear display name -> login, when it differs from the GitHub login
```

Put a personal API key in `.env` as `LINEAR_API_KEY` (Linear: Settings, Security and access,
Personal API keys). Fetch checks that the key belongs to `workspace` before it pulls anything.
People are identified by their Linear display name; use `people.aliases` to map a name to the
login the GitHub source uses, so one person stays one node. Pull requests become links
(`MENTIONS`) only when the attachment URL matches a pull request from the GitHub source.

## Synthetic tickets in a real Linear workspace

`companies/synthetic_linear.yaml` is the synthetic company with its tickets read from a real
Linear workspace instead of the offline JSONL (`companies/synthetic.yaml`). It is a second slug
on purpose: offline and live uids differ, so one company with both would hold every ticket twice.

1. Create a free Linear workspace and set `workspace:` in `companies/synthetic_linear.yaml` to
   its URL key.
2. Create the teams Identity (`IDN`) and Payments (`PAY`).
3. Invite four accounts you control. Set their display names to `alice`, `bob`, `carol` and
   `erin`, and add them to the teams (alice and carol: IDN; bob and erin: PAY).
4. Put a personal API key in `.env` as `LINEAR_API_KEY`.
5. Fill the workspace. Without `CONFIRM=1` this only prints the plan:

   ```bash
   make linear-seed SLUG=synthetic_linear              # plan: workspace and counts, writes nothing
   make linear-seed SLUG=synthetic_linear CONFIRM=1    # creates 10 tickets, 4 blocks, 4 PR links
   ```

   The command refuses a company that is not `synthetic`, checks that the workspace, teams and
   users exist before it writes anything, and records progress in
   `data/raw/synthetic_linear/linear/<workspace>/seed_state.json`. A stopped run resumes where
   it stopped; a finished one creates nothing when run again.
6. Build the graph and compare with the offline one:

   ```bash
   make schema SLUG=synthetic_linear && make sync SLUG=synthetic_linear
   make query SLUG=synthetic_linear TOOL=blocked_on P="login=carol"
   ```

## Jira (planned)

There is no Jira adapter yet. It would produce the same canonical tickets: Jira statuses map to
`status_category` through the status category key, priorities to urgent/high/medium/low, "Blocks"
links to `BLOCKS`, and accounts to logins through `people.aliases`. The full field mapping is in
[section 6 of the Linear adapter design](superpowers/specs/2026-10-16-linear-adapter-design.md).

## (c) A synthetic company for demos

`companies/synthetic.yaml` points at
[`apps/backend/examples/synthetic_company/`](../apps/backend/examples/synthetic_company/): 5
people and a bot, 2 teams, 4 systems, 15 work items, with known answers built in (one system
whose declared owners are not the people doing the work, a bot that must not count as an
expert, two systems that change together).

```bash
make synthetic                        # regenerate the JSONL, create the schema, full ingest
make query SLUG=synthetic TOOL=owners_vs_experts
```

Copy `generate.py` to make your own demo company: edit the Python data at the top, run it, and
point a new `companies/<slug>.yaml` at the output folder.
