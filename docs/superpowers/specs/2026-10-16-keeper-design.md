# The Keeper: design

Status: draft for approval, 2026-10-16. Replaces the "Brain Curator" in README.md and
docs/architecture. The MCP server is out of scope here and will be designed later.

## Intent

The brain answers from what the sources say. When it can't answer, or what it says is out of
date, nobody fixes it. The **Keeper** is the agent that reviews the graph and updates it, so
each failed question makes the brain better for the next person. It consults the `pm` and `qa`
agents, applies a fixed rule to decide whether a lead must approve an update, and logs
everything it does so a person can see what changed and why.

The simulation is no longer the story. Agents act on what the Keeper writes, not on simulated
sprints.

## Goals

1. Every failed Ask turn (no answer, zero sources, thumbs down) becomes a **gap** for the Keeper.
2. After every build, cheap fixed queries **notice** problems (for example stale owners) and add
   them as gaps.
3. A budgeted **review run** fixes the top gaps. `pm` and `qa` are consulted, the Keeper writes a
   claim, and a fixed rule decides whether it goes straight in or waits for a lead.
4. A lead approves or rejects critical updates in the app.
5. Every Keeper action is **logged**: what, why, evidence, who approved it (or "auto"), when.
6. Ask **uses the Keeper's knowledge** and cites it, so asking the question again shows the fix.
7. `pm` **reacts** to accepted updates by opening a follow-up task.

## Non-goals

- The MCP server (later).
- Routing gaps to an expert, or a form for people to answer them. A gap the agents can't ground
  is only marked **needs a person** and left visible.
- A designer agent, and the roles `developer`, `devops`, `reviewer`, `risk` in the demo. Their
  code stays.
- Deleting the simulation code. It stays and is no longer promoted.
- Real FalkorDB ACL users and the rest of the phase-2 work store (`queries/work/*`). In scope:
  a FalkorDB store for `keeper_<slug>` only, which answers the `keeper/*` named queries, so
  `runner.run_job` can run the new jobs. `acl.py` learns a `keeper_` graph kind (written by
  `keeper`, `pm` and `qa`, read by all). Episodes of these jobs become ledger LogEntries.

## Anti-goals

- **The Keeper changes ingested facts.** It never edits nodes or edges the loader owns; a re-ingest
  would overwrite them, and the sources stay the record of what happened.
- **Anything is deleted.** Old claims get `valid_to` and status `superseded`; rejected ones stay
  with the reason.
- **"Critical" is the model's opinion.** It is a fixed rule in code, so it can be tested and explained.
- **An update that cites nothing real.** Every claim's evidence uids must exist in the graph.
- **LLM-written Cypher.** All reads and writes are named `.cypher` files, as everywhere else.

## Agents

Role names, as in `apps/agents/agents/roles`:

| Role | Job |
|---|---|
| `brain` | Answers questions (Ask). Unchanged, apart from reading Keeper claims. |
| `keeper` | New. Reviews gaps, decides on a claim, the only agent that writes knowledge. It replaces `builder` and `critic` in the demo: it is the single writer of knowledge, and its supersede/contradict check replaces the Critic's. It does **not** mine decisions from released work; gaps are its only input. |
| `pm` | Consulted on gaps; reacts to accepted updates by opening a follow-up task. |
| `qa` | Consulted on gaps (regression risk, test evidence). |

Agents never call each other: the Keeper posts consult items, `pm` and `qa` find them in their
queues and answer, and the Keeper reads the answers. These are ordinary jobs (`roles/base.py`
`Job`: queue, optional claim, one submit tool, apply) run by `runner.run_job`. Each new job gets
a deterministic offline policy (`agents/policies`), so `make test` never calls the API.

## Sources win

When a Keeper claim disagrees with what the sources say, **the source is accepted** (user
decision). The Keeper fills in what the sources don't say; it never overrides them.

- A claim that contradicts an ingested fact never becomes knowledge. It is stored with status
  `conflicts_with_source`, is not projected into the brain, and is logged with both sides. `pm`
  opens a FollowUp to fix the source, for example "update CODEOWNERS for Billing". When a later
  ingest brings the fixed source, the brain is right on its own.
- "Ingested fact" here means the declared `OWNS`, the top of `experts_for_system`, and any
  property or edge the loader writes about the claim's subject.
- After every build, each accepted claim is checked again against the new sources. A claim the
  sources now contradict is marked `superseded` by the source and logged `claim_superseded`, with
  the source node as the reason.
- Ask presents source facts as the answer. It uses Keeper claims only for what the sources don't
  cover, and says when a part of the answer comes from the Keeper. The owner and expert tools are
  therefore unchanged; `keeper_notes` and `get_entity` are enough.

## Where the data lives

A rebuild deletes `brain_<slug>` (`backend/jobs.py` `reset` calls `db.delete_graph`), so the
Keeper's records cannot live only there.

- **`keeper_<slug>`: the ledger, and the source of truth.** It holds gaps, consults, claims of
  every status, follow-up tasks and the log. It points at brain nodes by uid string (the same
  pattern Risk findings use) and survives rebuilds. `backend reset` deletes it with the others.
- **`brain_<slug>`: accepted claims, projected.** Each accepted claim is written into the brain as
  a `Claim` node with real `ABOUT` and `EVIDENCE` edges, so Ask, `get_entity`, `path_between` and
  the Graph page see it as part of the graph. Projection is idempotent (`MERGE` on uid) and runs
  after every accept and after every build, which restores claims a rebuild removed. Ingest never
  touches the `Claim` label.

All reads and writes are named queries in `apps/brain/queries/keeper/*.cypher`. They are run
through `brain/db.py`, which learns to select `keeper_<slug>` as well as `brain_<slug>`. Agents
reach the ledger through one small brain entry point, in the same way `brain.tools.call` serves
reads, so `test_package_boundaries.py` keeps passing.

### Records (ledger)

- **Gap** `{uid, kind, text, status, count, priority, created_at, updated_at, trace_ids,
  about: [uid]}`.
  - `kind`: `failed_question`, `thumbs_down`, or a noticing kind such as `stale_owner`.
  - `status`: `open`, `in_review`, `resolved`, `needs_person`, `dismissed`.
  - Dedupe: the same kind and normalised text (or the same kind and subject, for noticing gaps)
    bumps `count` instead of adding a second gap.
- **Consult** `{uid, gap, role, status, answer, cites, can_ground}`: one per role per gap.
- **Claim** `{uid, kind, subject, statement, value, evidence: [uid], status, critical,
  critical_reasons, valid_from, valid_to, author, approved_by, gap}`.
  - `approved_by` is the name the lead types in the app. The app has no sign-in, so it is
    recorded, not verified.
  - `kind`: `owner`, `expert`, `decision`, `fact`, `link`. This one label replaces the spec's
    planned `Decision` node; `docs/graph-model.md` and `docs/agents.md` are updated to match.
  - `status`: `pending_approval`, `accepted`, `rejected`, `superseded`, `stale`,
    `conflicts_with_source`.
  - `stale`: after a build, projection reports any accepted claim whose subject or every evidence
    uid is gone from the brain. Such a claim is marked `stale` (logged `claim_stale`, not
    projected) and its gap reopens.
- **FollowUp** `{uid, claim, title, body, by: "pm", status}`: the task `pm` opens.
- **LogEntry** `{uid, at, actor, action, why, gap, claim, evidence}`. Append-only. Actions include
  `gap_opened`, `consulted`, `claim_written`, `claim_queued`, `claim_approved`, `claim_rejected`,
  `claim_superseded`, `needs_person`, `follow_up_opened`.

## The review run

One bounded run, started after a build or by **Review now**:

1. **Pick** the top `KEEPER_BUDGET` open gaps (default 5). Failed questions come first, then by
   `count`, then by age.
2. **Consult.** Post one consult per gap for `pm` and one for `qa`, then run their consult jobs.
   Each answers with a draft claim citing uids it saw, or with `can_ground: false`.
3. **Decide.** The `keeper` job reads the gap and both answers, then submits one of three things:
   a claim, `needs_person` (nobody could ground it), or `dismiss` (the gap was noise), with a reason.
4. **Check (deterministic).**
   - Every evidence uid must exist in `brain_<slug>`; otherwise the claim is rejected and logged.
   - A claim that contradicts an ingested fact becomes `conflicts_with_source` (see "Sources win").
     It is not written into the brain, and it skips approval.
   - Then the critical rule below is applied.
5. **Write.**
   - Not critical: accepted at once, projected into the brain, and the gap resolved.
   - Critical: `pending_approval`, and the gap stays `in_review` until a lead acts.
   - An accepted claim with the same kind and subject as an earlier one supersedes it (`valid_to`
     is set).
6. **React.** The `pm` react job opens a FollowUp for each `conflicts_with_source` claim (fix the
   source) and for each accepted claim of kind `owner`, `expert` or `decision`.
7. **Log** every step. Progress streams as events, the same way builds and Ask do.

Rough cost: with 5 gaps, about 15–20 job runs of a few model calls each. A Review now press takes
minutes on Haiku, so the run streams progress and can be stopped between steps.

### Running it

- The post-build review is its **own background job**, started when a build completes. It does
  not hold a build slot and does not delay "build done".
- There is **one review per company at a time**. Review now during a running review returns the
  running one, so the UI simply attaches to its progress.
- **No `ANTHROPIC_API_KEY`:** re-projection and noticing still run, and the review is skipped with
  a log entry `review_skipped` ("no API key"). The CLI `--offline` runs the scripted policies
  instead, for tests and keyless demos.
- A restart marks a running review `stopped`, as builds are.

### Gap lifecycle

- Noticing skips a subject that already has an accepted claim of the matching kind, or an open
  FollowUp to fix its source. A stale owner already being fixed is not raised again.
- Dedupe bumps `count` only on gaps that are `open` or `in_review`. A resolved gap never reopens
  from noticing; a new failed question with the same text opens a fresh gap that links the old one.
- A rejected claim sends its gap back to `open` and adds one to `attempts`. After 2 attempts the
  gap becomes `needs_person`.

### Critical rule (fixed, in code)

A claim is critical if any of these hold, whatever the model said:

1. **It replaces an earlier Keeper claim.**
   - An accepted claim with the same `kind` and `subject` already exists.
   - Or, for `decision`, any accepted decision claim exists about the same system.

   A claim that contradicts the sources doesn't get here; see "Sources win".
2. **It touches a high-impact system.** One of its `about` systems is in the top 25% of systems by
   how many other systems co-change with it (`impact_of` row count). This is computed by one named
   query.
3. **It has no source evidence.** None of its evidence uids is a `Change`, `WorkItem` or
   `Document`.

The reasons are stored in `critical_reasons` and shown to the lead.

## Triggers

- **Failed question.**
  - When an Ask turn's trace is written with no answer or zero sources, a gap is opened. This is
    in `agents/traces.py` or the Ask worker.
  - A thumbs-down on a turn opens or bumps a gap too.
- **After a build.** `backend/jobs.py` runs these steps when a build completes:
  1. Re-project accepted claims.
  2. Run the noticing queries. There are at least two to start with: `stale_owner` (from
     `owners_vs_experts`) and one more of the builder's choice.
  3. Start a review run with a small budget (default 3).

  On a company's first build, noticing is capped so a fresh brain doesn't flood the queue.
- **Review now.** An API route and `agents keeper review SLUG` start a run with `KEEPER_BUDGET`.

## Ask reads the Keeper's knowledge

- A new named read tool `keeper_notes` returns the accepted claims about a uid, with their
  evidence.
- `get_entity` neighbours include `Claim` nodes. Claim uids enter the toolset's seen set, so
  answers can cite them.
- `system_prompt.md` gets one rule: sources come first, and Keeper claims are only for what the
  sources don't cover, labelled as such. The prompt stays static, so it remains cacheable.
- The Graph page draws `Claim` nodes. The territory of a claim is its `ABOUT` system.
  `queries/graph/*`, `graph_view.py` and the frontend types are extended.
- When a gap from a failed question is resolved, its question becomes a draft eval case, tagged
  `draft` like `eval-drafts`.

## Surfaces

- **CLI:**
  - `agents keeper notice|review|gaps|log SLUG`
  - `make keeper-review SLUG=...` and `make keeper-notice SLUG=...`
- **API** (backend), under `/api/companies/{slug}/keeper/`:
  - list gaps
  - list claims by status
  - approve or reject a claim (body: who, why)
  - the log
  - start a review (SSE progress)
- **UI** (frontend): a Keeper page per company with Gaps, Approvals, Log and Review now. Ask
  answers show when they cite a Keeper claim. **Every screen goes through the
  `/design-directions` skill (mockups first, user picks) before UI code**, checked against
  `apps/frontend/design-system.md`.
- **Docs:**
  - README.md and docs/architecture: rename Brain Curator to Keeper, show four agents, drop the
    designer.
  - docs/agents.md and docs/graph-model.md: add the Keeper, the ledger and `Claim`.
  - CLAUDE.md: the new pieces.

## Constraints

- Dependency rule backend → agents → brain. Only `brain/db.py` opens FalkorDB.
- Named queries only, each with its `//` header.
- Offline policies for every new job. `make test` has no API calls; graph tests use throwaway graphs.
- Frontend components read tokens only. New components are exported and shown in `/components`.

## Cut line (deadline Oct 18)

- **Must:**
  - ledger and projection
  - gaps from failed questions and thumbs-down
  - the review run with consults
  - critical rule and approval API
  - log
  - `keeper_notes` and Ask citing claims
  - `pm` follow-up
  - CLI
  - a minimal Keeper page (gaps, approvals, log, Review now)
  - README and diagram rename
- **Stretch:**
  - noticing beyond `stale_owner`
  - draft eval cases from resolved gaps
  - Graph page polish for claims
  - a `qa` reaction
  - MCP (separate design)

## Left to the builder

- Exact field names, uid formats and the noticing queries beyond `stale_owner`.
- Prompts for the `keeper` / `pm` / `qa` consult and react jobs.
- How progress events are shaped, as long as they match the build/Ask SSE style.

## Calls made in this design (not discussed with the user)

- A separate `keeper_<slug>` ledger plus projection into the brain, because rebuilds delete
  `brain_<slug>`.
- One `Claim` label with a `kind`, replacing the planned `Decision` node.
- `builder` and `critic` leave the demo; the Keeper takes their jobs.
- Review budget 5 on demand and 3 after a build; noticing capped on a company's first build.
- "High impact" means the top 25% of systems by co-change count.
- A rejected claim sends its gap back to `open`; after 2 attempts it becomes `needs_person`.
- The post-build review is a separate background job, one review per company at a time, skipped
  without an API key.
- A minimal FalkorDB store for `keeper_<slug>` and a `keeper_` ACL graph kind are in scope.
- The approver is a typed name, recorded but not verified (the app has no sign-in).
- Claims whose subject or evidence disappears after a rebuild become `stale` and reopen their gap.
- A claim that contradicts the sources becomes `conflicts_with_source`, with a `pm` FollowUp to fix the
  source. The owner and expert tools stay unchanged. (The rule itself, sources win, was the user's
  decision.)
