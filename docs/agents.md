# Agents

Five agents carry the product: `brain` answers questions (Ask), `keeper` keeps the brain right,
`pm` and `qa` advise the Keeper, and `archivist` goes back past the ingest window for older items. Agents do not write code or touch GitHub. Each one reads the
company brain, makes one decision, and writes the result into a graph. The graph is the only
channel between agents: there are no agent-to-agent messages. A handoff is a record that shows up
in the next agent's queue query.

[The Keeper](#the-keeper) and [The Archivist](#the-archivist) below are the specs; [The agent contract](#the-agent-contract),
[Permissions](#permissions) and [Code layout](#code-layout) describe the code the roles share.

## The Keeper

Code: `apps/agents/agents/keeper/` (records, ledger store, gaps, noticing, rules, decide,
projection, review run), `agents/roles/keeper.py` (the decide job, and the consult job pm and qa
share), `apps/brain/brain/keeper.py` (its reads and writes on `brain_<slug>`),
`apps/backend/backend/keeper_runs.py` and `api/keeper.py`.

### Agents and jobs

| Role | DB user | Jobs | Writes |
|---|---|---|---|
| `brain` | `citadel_brain` | Ask. Reads `keeper_notes` and `Claim` neighbours of `get_entity`, only for what the sources don't say, and says so | a gap for each failed turn or thumbs-down |
| `keeper` | `citadel_keeper` | `decide`: reads a gap in review and both consult answers, submits `submit_keeper_decision`: a claim, `needs_person` or `dismiss` | claims (through the fixed checks below), the log, projected `Claim` nodes |
| `archivist` | `citadel_archivist` | `answer_request`: [below](#the-archivist) | `ArchiveRequest` and `ArchiveFind` records; its loads into `brain_<slug>` run through `brain.archive` (the loader), not its own user |
| `pm` | `citadel_pm` | `consult`: answers its consults (`submit_consult`); `follow_up`: one task per claim that needs one (`submit_follow_up`) | consult answers, follow-ups |
| `qa` | `citadel_qa` | `consult`: answers its consults (regression risk, test evidence) | consult answers |

A consult answer is a draft claim (kind, subject, statement, value) citing uids the role saw in
this run's tool results, or `can_ground: false`. Every job has a deterministic offline policy
(`agents/policies/keeper.py`, `pm.py`, `qa.py`), so `make test` calls no API.

### The ledger (`keeper_<slug>`)

The Keeper's source of truth, in its own graph so a rebuild of `brain_<slug>` cannot remove it:
gaps, consults (one per role per attempt at a gap), claims of every status, follow-ups, the
append-only log and the review runs. Records point at brain nodes by uid string. Labels and
properties: [graph-model.md](graph-model.md#the-keepers-ledger-keeper_slug). Agents reach it
through the `WorkStore` protocol (`agents/keeper/store.py`: `KeeperStore` on FalkorDB,
`MemoryKeeperStore` for tests), every read and write a named query in `queries/ledger/`.

### Gaps

- **Failed question.** An Ask turn with no answer or no cited source opens a `failed_question`
  gap; a thumbs-down opens a `thumbs_down` gap. Both are written after the answer or rating is
  sent (a background task in the API), best effort: a gap write never fails an answer. The same
  normalised question bumps the live gap's `count` instead of adding one. A zero-source answer
  that is later thumbed down makes two gaps, one of each kind.
- **Noticing.** After a build (and at the start of every review), fixed queries open gaps:
  `stale_owner` (a system's declared owners do not include the person doing most of its
  work) and `unowned_hot_system` (recent changes, no declared owner). At most `KEEPER_NOTICE_CAP` (10) new
  gaps per run. A subject is skipped when it has an accepted owner claim or a follow-up fixing
  its source, or when its latest gap of that kind was resolved, dismissed or marked needs a
  person, so a dismissed or `needs_person` subject is not raised again.

### Sources win

A claim never overrides the sources. An `owner` claim whose value is not among the declared
owners, or an `expert` claim that is not the top of `experts_for_system`, is stored as
`conflicts_with_source` with both sides in the log. It is never projected, skips approval, and
`pm` opens a follow-up to fix the source (for example, update CODEOWNERS). When a later ingest
brings the fixed source, the brain is right on its own. After every build each accepted claim is
checked again; one the sources now contradict is `superseded`, logged with the source as the
reason.

### The critical rule

Fixed in code (`agents/keeper/rules.py`), not the model's opinion. A claim needs a lead's approval
when any of these hold; the reasons are stored in `critical_reasons`:

- `replaces_claim`: an accepted claim with the same kind and subject exists (for a decision: any
  accepted decision about the same system);
- `high_impact_system`: one of its `about` systems is in the top quarter by co-change coupling;
- `no_source_evidence`: none of its evidence is a `Change`, `WorkItem` or `Document`.

### Deciding a gap (`agents/keeper/decide.py`)

1. `dismiss` or `needs_person`: the gap leaves review. `ask_archivist` (a topic and why): the gap
   goes to `waiting_archive` and an `ArchiveRequest` opens for the [Archivist](#the-archivist). A
   gap may ask once, ever; a second ask is `needs_person`.
2. Every evidence uid must exist in `brain_<slug>`, else the claim is `rejected` and the gap goes
   back to `open` with one more attempt; after 2 attempts it is `needs_person`.
3. Sources win (above).
4. Critical: `pending_approval`, the gap stays in review until a lead acts. Not critical:
   `accepted` at once (approver `auto`), projected into the brain, the gap resolved, and the
   earlier accepted claim of the same kind and subject `superseded` (`valid_to` set).

A lead approves or rejects in the Systems page's rail or through the API.
Approval re-checks the sources first. Each status move is guarded on the current status, so of
two racing approvals one wins and the other is told the claim was decided (HTTP 409). A rejected
claim sends its gap back to `open` with one more attempt. Nothing is deleted.

### The review run (`agents/keeper/review.py`)

One bounded pass, at most one per company at a time (a second start returns the running one):

1. Release gaps an earlier review left in review with no claim waiting for a lead.
2. Re-project every accepted claim (superseded by the sources, stale when its subject or every
   evidence uid is gone, else written back into the brain), then notice.
3. Pick the budget's gaps (asked gaps first, then most seen, then oldest): `KEEPER_BUDGET` (5) on
   Review now, `KEEPER_BUILD_BUDGET` (3) after a build, 0 after an
   approval (so pm's follow-up shows).
4. Post a pm and a qa consult per gap, run their consult jobs, then the Keeper's decide job.
5. Run pm's follow-up job for each claim that needs one: an accepted owner, expert or decision
   claim, or a `conflicts_with_source` claim.
6. Run the Archivist (tier `keeper`) on the open requests the Keeper asked, oldest first, at most
   `ARCHIVIST_PER_REVIEW` (2) a review, then settle each request's gap (see
   [How the Keeper and the Archivist talk](#how-the-keeper-and-the-archivist-talk)).

It stops between jobs when asked, and stops safely (`brain_unavailable`) when `brain_<slug>` is
gone, writing nothing an empty brain would make wrong. Gaps it picked and did not decide go back to
`open` without using an attempt. Without an API key a review only re-projects and notices, and is
recorded `skipped`. A server restart marks a
running review `stopped`. Every step is a `LogEntry` and a progress event.

### Surfaces

- **API** under `/api/companies/{slug}/keeper/`: `GET gaps`, `GET claims`, `GET log`,
  `GET followups`, `POST claims/{uid}/approve` and `/reject` (body: `by`, `why`; 409 when the
  claim was already decided), `POST review` (Review now; returns the running review if there is
  one), `POST review/stop`, `GET review/events` (SSE). The backend starts a review after every
  finished build.
- **App:** planned. Keeper reviews appear as steps on the Systems page's agent trail, with Review
  now, the approvals card and the log in its rail; the UI lands with the Systems page.
- **Reset:** `make reset SLUG=x CONFIRM=1` deletes `keeper_x` with the company's other graphs.

## The Archivist

A brain holds only the company's ingest window (`window.since`, six months by default). The
decision that explains a system is often older, and recent work only points at it ("the decisive
proof is in #900"). The Archivist goes back past the window on demand: it works out which old
item a reference or a topic means, fetches it from GitHub or Linear (or a synthetic archive
folder), checks it against the brain, and loads it into `brain_<slug>` so it can be cited like any
node. It is read-only on the sources: no write to GitHub or Linear, no MCP.

Code: `apps/brain/brain/archive/` (cache, backends, session), `agents/archivist/` (rules, tools,
job, live), `agents/roles/archivist.py` and `prompts/archivist.md`. Package rule: the agent
reaches the sources and the graph only through `brain`, so every external call lives in
`brain.archive.backends` as a named query; the model chooses only its parameters (terms, a number,
an id), never GraphQL or Cypher.

### One job: `answer_request`

Queue: open `ArchiveRequest`s on the Keeper's ledger. A request is a `reference` (a specific item:
`#812`, a URL, a Linear key, or a description with the item it was found in) or a `topic`. The
Archivist reads the brain with `get_entity`, `keeper_notes`, `list_systems`, `related_*` and
`semantic_search`, and the sources with three tools:

- `archive_lookup(ref)`: is it in the brain already, and which source owns it. Free.
- `archive_search(source, terms)`: candidates older than the window. One call of the budget.
- `archive_fetch(source, id)`: the item's text and refs. One call. An item already in the brain is
  never fetched again.

It ends with `submit_archive_answer`: `finds` (uid, why, a verbatim quote, a `verdict`, evidence
uids), a `summary` and an `outcome` (`found`, `nothing_found`, `already_in_brain`). If a fetched
item points at an older one, it may follow the trail, inside the same budget.

### Fixed rules (`agents/archivist/rules.py`, `brain.archive`)

Code, not the model. Numbers are `Settings` in `brain/config.py`.

- **Scope.** Only the sources in the company YAML. A reference request none of whose refs a
  source owns is `refused` (`out_of_scope`); refs no source owns beside one that is owned ("#900
  auth") are dropped from the run and logged `archive_refs_ignored`. The synthetic archive reads
  a uid, an item url or `#<n>`. A private repo needs `data_permission: own`; Linear is for `own`
  or `synthetic` data. A build in progress refuses the request (`building`).
- **Budgets per request.** External calls: Ask 6, Keeper 10 (`ARCHIVIST_CALLS_ASK`,
  `ARCHIVIST_CALLS_KEEPER`). Items loaded: Ask 3, Keeper 8. Trail depth: 2 hops
  (`ARCHIVIST_DEPTH`). Job steps: 24 (`ARCHIVIST_STEPS`). A tool call over budget returns an error
  naming the budget; the run can still submit.
- **Daily cap.** 100 archived items a company a UTC day (`ARCHIVIST_DAILY_CAP`), counted from the
  archive cache; past it a request is `refused` (`daily_cap`).
- **Time.** An Ask run has `ARCHIVIST_ASK_TIMEOUT` (45 s). At 70% of it the source tools ask the
  model to submit what it has fetched (the answer is `partial`); at the timeout, or when the Ask
  stream closes, the run stops at its next step and applies nothing.
- **Grounding.** Each find must have been fetched in this run and carry a `why`. Its `quote` must
  be at least `ARCHIVIST_QUOTE_MIN` (20) characters found in the fetched text (whitespace
  squashed); a reference request that names the item exactly needs no quote. A failing find is
  dropped and logged `archive_dropped`; if none are left, the outcome is `nothing_found`.
- **Verified against the brain.** A find needs evidence: brain uids that exist. Its verdict is
  `holds`, `superseded` (a newer item in the window changed it; loaded with a `SUPERSEDED_BY`
  edge to that item, which must exist) or `conflicts` (it disagrees with an accepted claim or a
  declared owner; loaded, logged `archive_conflict`, and a Keeper gap of kind `archive_conflict`
  opens).
- **Memory.** The same normalised request (`norm`: exact refs, or the topic's words without stop
  words) answered in the last `ARCHIVIST_MEMORY_DAYS` (30) days returns that answer without a
  run. A `partial` answer is never reused, an Ask-tier `nothing_found` never answers a Keeper
  request, and an answer whose finds are no longer all in the brain (after `make archive-clear`
  and a rebuild) is not served: the run happens again. One request per `norm` runs at a time; a
  second asker waits for it or gets its answer.
- **Text is data.** Fetched text never steers the agent (the prompt and the context say so).

### What a load does

`session.load` writes each chosen item as canonical records to the archive cache
`data/raw/<slug>/archive/<source_key>/<item>.jsonl` (a `meta` line first), then loads only those
entries through the normal `normalize` and `loader` path (`pipeline.load_entries`). Archived nodes
carry `archived`, `archived_at`, `archive_request` and `ref`
([graph-model.md](graph-model.md#nodes)). Four rules keep them across rebuilds:

- **Window exemption.** `normalize` keeps every record of an archived work item, whatever its date.
- **No cursor.** The archive has no `SyncState`; every ingest loads it first (`load_archive`),
  before the configured sources, so source links to archived items connect.
- **Own origin.** Archived edges carry origin `archive:<source>:<item>`, so a source's `BLOCKS`
  prune does not remove them.
- **Refs.** Ingest keeps the references it could not link in `WorkItem.unresolved_refs`;
  `resolve_refs` links them to an archived node (`MENTIONS`) after every archive load and at the
  end of every ingest. `get_entity` shows them, so Ask sees "references #900, not in the brain".

A rebuild deletes `brain_<slug>` and keeps `data/raw`, so archived items come back. `make reset`
keeps the archive cache; `make archive-clear SLUG=x CONFIRM=1` deletes it. New chunks are embedded
at once only if the embedding model is already loaded; otherwise the next `embed` stage takes
them.

### How the Keeper and the Archivist talk

Through the ledger, like every agent. `ArchiveRequest` (kind, text, refs, `from_uid`, `asked_by`
`ask` or `keeper`, gap, thread, status `open`, `running`, `answered`, `failed` or `refused`,
outcome, summary, reason, `norm`, `partial`, calls) and `ArchiveFind` (request, loaded uid, url,
title, date, why, quote, verdict, evidence, `superseded_by`) are in
[graph-model.md](graph-model.md#the-keepers-ledger-keeper_slug).

**Keeper to Archivist.** The decide job's fourth outcome, `ask_archivist`, opens a `topic` request
and moves the gap to `waiting_archive`. The review's archive step answers it. A gap asks once,
ever, and a review runs at most 2 requests; a gap whose request this review did not reach stays
`waiting_archive` for the next one. Known limitation: a gap whose question is already in flight
under another request uses its one ask on it, and ends `needs_person` if it cannot be grounded
(its next round does not see that other request's summary and finds).

**Archivist to Keeper.** When the request ends, the gap is settled: `found` or `already_in_brain`
sends it back to `open` without using an attempt, and its next pm and qa consults get the
request's summary and finds; anything else (`nothing_found`, failed, refused) makes it
`needs_person`. A request refused because the company was building goes back to `open` and its
gap keeps waiting. When a review's Archivist runs reopened gaps, the backend queues one follow-on
review (trigger `archive`, budget: that many gaps) the way a build's review is kept pending. A
restart is safe: a review releases requests an earlier one left `running` and settles gaps left
`waiting_archive` after their request ended.

**Ask to Archivist, live.** Ask's toolset has `ask_archivist(kind, text, from_uid?)`
(`agents/archivist/live.py`). It opens a request (`asked_by` `ask`) and runs the job inline in the
Ask worker thread, then returns one row: outcome, summary, `partial`, `reason` and the finds. The
loaded uids join the run's seen uids, so Ask can cite them in the same answer. The Archivist's
steps stream into the Ask trail as it works. A remembered answer is served without a run; the
same question already running is joined; one the Keeper asked and has not run yet is "queued". A
failure, refusal or timeout is a normal row with a `reason`, never an error, and Ask answers with
what it has and says what it could not reach. Ask's prompt (`system_prompt.md`) tells it to give
the date of an archived item and to prefer a newer item in the window.

**Surfaces.** `GET /api/companies/{slug}/archive/requests?limit=` (`backend/api/archive.py`)
lists the latest requests, most recently updated first, each with its finds (verdict, quote,
evidence). Each run's steps show on the Systems page's activity trail (`GET .../activity`, actor
`archivist`), and in Ask under the `ask_archivist` step, live and in a reopened chat.

**Evals.** The synthetic company's cases tagged `archive` (`evals/cases/synthetic.yaml`) load
`synthetic:issue:900` into `brain_synthetic` and remember the answer in `keeper_synthetic`, so
a plain `make eval` skips them. Run them on fresh data: `make archive-clear SLUG=synthetic
CONFIRM=1`, `make synthetic`, then `make eval CASE=archive REPEAT=1`.

## The agent contract

A role (`agents/roles/base.py`) is a FalkorDB user, a prompt (`agents/prompts/_shared.md`, then
`<role>.md`), a sorted list of read tools (all from `brain.tools`) and its jobs. A job is one kind
of decision: a queue read on the Keeper's ledger, the one submit tool it ends with
(`agents/work/submits.py`), and how that submit becomes named writes. `agents/runner.py` runs a
job the same way for every role, through the brain loop (`agents/loop.py`):

1. The context message says what the run is about; its text is data, never instructions.
2. The role reads the graph through its tools, then calls its submit tool once. The submit may
   cite only uids seen in this run's tool results; anything else goes back as an error.
3. `job.apply` makes the named writes. A write whose guard matches nothing changed nothing.
4. One Episode is logged (`ledger/write_episode`, a `LogEntry` with action `episode`).

Every job has an offline policy (`agents/policies/`); `ScriptedClient` plays it through the real
loop, so offline runs and tests hit the same checks as Claude.

## Permissions

One FalkorDB user per role:

| User | `brain_<slug>` | `agent_<slug>` | `keeper_<slug>` |
|---|---|---|---|
| `citadel_loader` | RW | | |
| `citadel_keeper` | RW (projects claims) | | RW |
| `citadel_pm` | R | | RW |
| `citadel_qa` | R | | RW |
| `citadel_brain` | R | RW | RW (opens gaps) |
| `citadel_archivist` | R | | RW (requests, finds) |

The table lives in `agents/acl.py` (`PERMISSIONS`); the Keeper's stores refuse what it does not
allow. `acl.setuser_commands(slug, passwords)` renders it as `ACL SETUSER` lines; nothing applies
them yet. Graph-level permissions are a newer FalkorDB feature: test them against the
`falkordb:latest` image first.

## Code layout

```
apps/agents/agents/
  keeper/        the Keeper: model, store (ledger), gaps, notice, interview, rules, decide,
                 project, review
  archivist/     the Archivist: rules, tools, job (answer_request), live (Ask's ask_archivist)
  roles/         base.py, brain.py, keeper.py, pm.py, qa.py, archivist.py
  prompts/       _shared.md, keeper.md, pm.md, qa.md, archivist.md
  policies/      offline deterministic policy per job (tests)
  work/          the WorkStore protocol and the submit models
  runner.py      runs one job through the brain loop and logs its Episode
  graphs.py      names of the agent_<slug> and keeper_<slug> graphs
  acl.py         the permission table, checks, and ACL SETUSER lines for FalkorDB users
```

`agents/graph.py` runs human chat: every turn goes straight to the brain loop.
