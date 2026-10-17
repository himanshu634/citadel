# Agents

Four agents carry the product: `brain` answers questions (Ask), `keeper` keeps the brain right,
and `pm` and `qa` advise the Keeper. Agents do not write code or touch GitHub. Each one reads the
company brain, makes one decision, and writes the result into a graph. The graph is the only
channel between agents: there are no agent-to-agent messages. A handoff is a record that shows up
in the next agent's queue query.

[The Keeper](#the-keeper) below is the spec; [The agent contract](#the-agent-contract),
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

1. `dismiss` or `needs_person`: the gap leaves review.
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

The table lives in `agents/acl.py` (`PERMISSIONS`); the Keeper's stores refuse what it does not
allow. `acl.setuser_commands(slug, passwords)` renders it as `ACL SETUSER` lines; nothing applies
them yet. Graph-level permissions are a newer FalkorDB feature: test them against the
`falkordb:latest` image first.

## Code layout

```
apps/agents/agents/
  keeper/        the Keeper: model, store (ledger), gaps, notice, interview, rules, decide,
                 project, review
  roles/         base.py, brain.py, keeper.py, pm.py, qa.py
  prompts/       _shared.md, keeper.md, pm.md, qa.md
  policies/      offline deterministic policy per job (tests)
  work/          the WorkStore protocol and the submit models
  runner.py      runs one job through the brain loop and logs its Episode
  graphs.py      names of the agent_<slug> and keeper_<slug> graphs
  acl.py         the permission table, checks, and ACL SETUSER lines for FalkorDB users
```

`agents/graph.py` runs human chat: every turn goes straight to the brain loop.
