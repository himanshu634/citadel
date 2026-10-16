# Agents

Citadel runs a simulated software company. Agents do not write code or touch GitHub. Each one
reads the company brain, makes one decision, and writes the result back into the graph. The
graph is the only channel between agents: there are no agent-to-agent messages. A handoff is a
status change that shows up in the next agent's queue query.

This file is the build spec: shared model first, then one section per agent, then the
orchestrator, permissions, simulations and build order. What is built so far is listed in
[Implementation status](#implementation-status) at the end.

## Ground rules

1. **The graph is the only channel.** Agents read their queue from FalkorDB and write their
   result to FalkorDB. Nothing is passed in memory between agents.
2. **No LLM-written Cypher.** Reads go through named tools (`queries/tools/*.cypher`), writes go
   through named write queries (`queries/work/*.cypher`). The LLM only chooses tools and fills
   their parameters.
3. **Every action is grounded.** Each `Action` must cite uids that appeared in tool results in
   that run (the same rule `submit_answer` already enforces).
4. **One legal move per write.** Each write query checks the current state in its `WHERE`
   clause, so an agent can only make its own transition (QA cannot release a task, a developer
   cannot pass its own QA). A write that matches nothing means "someone else got there first"
   or "not allowed".
5. **Every agent is its own FalkorDB user** with ACL rules (see Permissions). Read-only agents
   cannot write even if a prompt tells them to.
6. **Every role has an offline policy.** A deterministic Python policy can stand in for the LLM,
   so simulations and tests run with no API key (same idea as `agents/offline.py`).

## Shared model

New labels and relationships in `brain_<slug>`, on top of the existing model in
[graph-model.md](graph-model.md).

```mermaid
graph LR
  Task -- FROM_ISSUE --> WorkItem
  Task -- ABOUT --> System
  Task -- DUPLICATE_OF --> Task
  Agent -- DID --> Action
  Action -- ON --> Task
  Action -- CITES --> Any["any node"]
  Episode -- BY --> Agent
  Episode -- PRODUCED --> Action
  Decision -- MADE_IN --> Task
  Decision -- AFFECTS --> System
  Decision -- SUPERSEDES --> Decision
  Decision -- CONTRADICTS --> Decision
  Release -- INCLUDES --> Task
  Release -- IMPACTS --> System
  Release -- NOTIFIES --> Person
  Task -- "SUGGESTED_REVIEWER {score}" --> Person
```

| Label | Key properties |
|---|---|
| `Task` | `uid`, `title`, `body`, `status`, `priority`, `qa`, `pm`, `assignee`, `lease_until`, `acceptance` (list), `plan`, `planned_files` (list), `report`, `created_ts`, `updated_ts` |
| `Agent` | `uid` (`agent:dev-1`), `role`, `db_user`, `model` |
| `Action` | `uid`, `kind`, `summary`, `ts`, `agent`, `task` |
| `Episode` | `uid`, `agent`, `run_at`, `tick`, `input`, `summary`, `tools_called` (list) |
| `Decision` | `uid`, `summary`, `rationale`, `valid_from`, `valid_to`, `status` |
| `Release` | `uid`, `name`, `ts`, `notes` |

**Task status:** `open → triaged → in_progress → done → released`, plus `rejected`
(duplicate or out of scope) and `blocked`.

**Gates on a done task:** `qa: pending → testing → passed | failed` and
`pm: pending → reviewing → accepted | changes_requested`. Either gate failing sends the task
back to `in_progress` with the same assignee.

**Action kinds:** `seeded`, `triaged`, `rejected`, `claimed`, `planned`, `completed`,
`qa_started`, `qa_passed`, `qa_failed`, `pm_accepted`, `pm_changes_requested`, `released`,
`decision_recorded`, `decision_superseded`, `contradiction_found`, `lease_expired`.

### Constraints (`queries/schema/constraints.cypher`)

The database enforces these, whatever an LLM produces:

- `UNIQUE` on `uid` for `Task`, `Action`, `Agent`, `Episode`, `Decision`, `Release`
  (each needs its range index on `uid` first, which `range_indexes.cypher` already creates for
  existing labels; add the new labels there).
- `MANDATORY` on `Action(agent, kind, ts)`, `Task(title, status)`, `Decision(summary, valid_from)`.

### Derived edges (`queries/derive/*.cypher`, run by `brain derive <slug>` after ingest)

Graph algorithms run on relationships, so two weighted projections are materialised from the
raw activity:

- `(Person)-[:COLLABORATES {w}]->(Person)`: one reviewed the other's PR, or both commented on
  the same work item, weighted by count and recency.
- `(System)-[:CO_CHANGES {w}]->(System)`: changed in the same commit, weighted by count.

Algorithm scores are then written back as properties so queue queries can sort on them:
`System.pagerank`, `Person.betweenness`, `Person.community`, `Person.harmonic`.

```cypher
// derive/co_changes.cypher
MATCH (a:System)<-[:TOUCHES]-(c:Change)-[:TOUCHES]->(b:System)
WHERE id(a) < id(b)
WITH a, b, count(c) AS w
MERGE (a)-[r:CO_CHANGES]->(b)
SET r.w = w
```

```cypher
// derive/system_pagerank.cypher
CALL algo.pageRank('System', 'CO_CHANGES') YIELD node, score
SET node.pagerank = score
```

### UDFs (`queries/udfs/`, loaded by `make schema` with `GRAPH.UDF LOAD REPLACE`)

- **FLEX** (FalkorDB's community library): `flex.sim.jaccard` for file-set overlap between
  tasks, `flex.text.jaroWinkler` for login alias matching at ingest.
- **`citadel` library** (our JavaScript):
  - `citadel.decay(ts, now, half_life_days)`: one recency weight used by every query.
  - `citadel.priority(pagerank, mentions, age_days, severity)`: the one priority formula that
    every queue sorts by, so all agents agree on what is urgent.

## The agent contract

Every role implements the same small interface (`brain/agents/roles/base.py`):

```python
class Role(Protocol):
    name: str                       # "qa"
    db_user: str                    # FalkorDB ACL user this role connects as
    read_tools: list[str]           # names from brain.tools.TOOLS
    write_tool: str                 # one submit_* tool, maps to one queries/work/*.cypher

    def queue(self, slug: str) -> list[TaskRef]: ...     # named query, ordered by priority
    def claim(self, slug: str, task: TaskRef) -> bool: ...  # atomic; False = someone else got it
    def act(self, slug: str, task: TaskRef) -> Action: ...  # LLM tool loop or offline policy
```

`act` reuses the existing brain loop (`agents/loop.py`) with a role prompt
(`brain/agents/prompts/<role>.md`), the role's read tools, and exactly one submit tool. The
submit tool's pydantic model is the write query's parameter model, so the LLM cannot write
fields the query does not take. Every run writes one `Episode`.

### Atomic claim (the pattern every queue uses)

FalkorDB runs write queries on a graph one at a time, so check-and-set in one query is safe
under any number of competing agents:

```cypher
// work/claim_task.cypher
MATCH (t:Task {uid: $task})
WHERE t.status = 'triaged' AND (t.assignee IS NULL OR t.lease_until < $now)
SET t.status = 'in_progress', t.assignee = $agent, t.lease_until = $now + $lease_s,
    t.updated_ts = $now
RETURN t.uid
```

No row back means the claim failed. Gate claims (`qa`, `pm`) are the same shape on their own
field.

---

## Core agents

### 1. PM agent

**Goal:** turn raw issues into well-formed, prioritised tasks, and later accept or reject
finished work against the acceptance criteria it wrote.

- **Tier:** 1
- **DB user:** `citadel_pm`, read-write on `brain_<slug>` and `sim_<slug>_*`, read on
  `mem_<slug>_*` (to pick up other agents' findings), read-write on `mem_<slug>_pm`.

**Job A: Intake and triage**

- **Wakes on:**
  - open issues with no task yet (`work/untasked_issues.cypher`), which it seeds as tasks;
  - tasks in `open`;
  - findings in the Risk agent's memory graph that have no task yet.
- **Reads:**
  - `related_work_items` (duplicates and history)
  - `semantic_similar_tasks` (new, vector)
  - `list_systems`
  - `work_history`
  - `System.pagerank`
- **Decides:** duplicate or not; the target system; priority; 2–4 acceptance criteria.
- **Writes:** `submit_triage` → `work/triage_task.cypher`
  - `open → triaged` with `priority`, `acceptance` and `ABOUT → System`;
  - or `open → rejected` with `DUPLICATE_OF`.

**Job B: Acceptance**

- **Wakes on:** `status = 'done' AND pm = 'pending'`.
- **Reads:** the task's own acceptance criteria, the developer's report, and the task's
  `Action` trail.
- **Writes:** `submit_acceptance` → `pm: accepted`, or `changes_requested` with the reason
  (which sends the task back to `in_progress`).

**Tier 3 extra: staffing.** Uses `Person.community` (label propagation) to group tasks by the
real collaboration cluster, and `algo.maxFlow` to check that developer capacity can cover all
P0 tasks before the sprint starts.

- **FalkorDB shown:** vector + full-text hybrid search, PageRank, the `citadel.priority` UDF,
  `MERGE` dedupe, constraints.
- **Done when:** given ten seeded issues including two near-duplicates, it creates eight
  triaged tasks and two `rejected` ones with `DUPLICATE_OF`, each with `ABOUT` and acceptance
  criteria.

### 2. Developer agent (run two or more)

**Goal:** claim work, plan a concrete implementation grounded in how the codebase really
changes, and report completion.

- **Tier:** 1
- **DB user:** `citadel_dev`, read-write on `brain_<slug>`, `sim_<slug>_*` and
  `mem_<slug>_dev`. All developer instances share the user but have their own `Agent` node.
- **Wakes on:**
  - `status = 'triaged'` and unassigned or with an expired lease, ordered by
    `citadel.priority` (it claims one atomically);
  - its own tasks sent back by QA or the PM.
- **Reads:**
  - `work_history` (similar past PRs in the system)
  - `files_for_system` (new: the files past commits touched in that system)
  - `experts_for_system` (who to ask)
  - `impact_of` (what else tends to change with it)
  - `conflicting_tasks` (new)
  - its own lessons from `mem_<slug>_dev`
- **Decides:**
  - which files to change;
  - the risks;
  - who to consult;
  - whether to proceed or pick another task if another in-progress task overlaps too much.
- **Writes:**
  - `submit_plan` → `planned_files`, `plan`, Action `planned`;
  - then `submit_completion` → `in_progress → done`, `qa = pending`, `pm = pending`, `report`,
    Action `completed`.
  - When rework comes back, it must address the QA or PM reason in the new report.
- **Conflict check:**

  ```cypher
  // tools/conflicting_tasks.cypher
  MATCH (t:Task {uid: $task}), (o:Task {status: 'in_progress'})
  WHERE o <> t AND flex.sim.jaccard(t.planned_files, o.planned_files) > $threshold
  RETURN o.uid, o.assignee, flex.sim.jaccard(t.planned_files, o.planned_files) AS overlap
  ```

- **FalkorDB shown:** atomic conditional writes, leases, the FLEX `jaccard` UDF, co-change
  data.
- **Done when:** five developer instances racing for three triaged tasks produce exactly three
  `claimed` actions and three distinct assignees, every time.

### 3. QA agent

**Goal:** test each finished task against the company's real history of regressions in that
area, and fail it with a concrete reason when the plan misses one.

- **Tier:** 1. The vector part is Tier 2; Tier 1 uses full-text.
- **DB user:** `citadel_qa`, read-write on `brain_<slug>`, `sim_<slug>_*` and `mem_<slug>_qa`.
- **Wakes on:** `status = 'done' AND qa = 'pending'` (it claims by setting `qa = 'testing'`).
- **Reads:**
  - `past_regressions` (new): fix PRs and bug issues in the task's system, found by full-text
    plus vector similarity over comment chunks, expanded through `Chunk-FROM->WorkItem`;
  - `work_history`;
  - the developer's plan and report;
  - its own lessons.
- **Decides:**
  - a short test plan built from the past regressions it found;
  - pass, or fail citing the specific regression the plan does not cover.
- **Writes:** `submit_qa` → `qa: passed`, or `qa: failed` with the reason. A failure also sets
  `status = 'in_progress'`, the task goes back to the same developer, and the Action cites the
  regression's uid.
- **Procedural memory:** after the same failure reason appears for the same system twice, it
  writes a `Lesson` to `mem_<slug>_qa` ("Indexing changes must cover the index rebuild path,
  see #123"). Lessons are read at the start of every QA run, and also by developers (the dev
  user has read access to `mem_<slug>_qa`).
- **FalkorDB shown:** HNSW vector index, full-text index, hybrid retrieval with graph
  expansion, per-agent memory graph.
- **Done when:** a seeded task whose plan omits a known regression fails, is reworked, then
  passes, and a lesson exists after the second occurrence.

### 4. DevOps / Release agent

**Goal:** ship accepted work in safe, independent batches, and tell the right people what
the release touches.

- **Tier:** 1
- **DB user:** `citadel_devops`, read-write on `brain_<slug>`, `sim_<slug>_*` and
  `mem_<slug>_devops`.
- **Wakes on:** `status = 'done' AND qa = 'passed' AND pm = 'accepted'`. It marks these with
  the label `:ReleaseCandidate`.
- **Reads:**
  - `release_trains` (new, WCC): splits candidates into groups that share no systems, so each
    group can ship on its own;
  - `blast_radius` (new, `SSpaths` over `CO_CHANGES` from each affected system, bounded by
    `maxLen`);
  - `experts_for_system` and declared owners (who to notify).
- **Decides:** release names, the release notes, and whether a train is too risky to ship
  this tick (for example a very large blast radius, which it holds for one tick).
- **Writes:** `submit_release` → a `Release` node with `INCLUDES` tasks, `IMPACTS` systems
  (with depth) and `NOTIFIES` people. Tasks become `released` and the `:ReleaseCandidate`
  label is removed.

  ```cypher
  // tools/release_trains.cypher
  CALL algo.WCC({nodeLabels: ['ReleaseCandidate', 'System'], relationshipTypes: ['ABOUT']})
  YIELD node, componentId
  WITH componentId, collect(node) AS members
  WITH componentId, [m IN members WHERE m:ReleaseCandidate] AS tasks
  WHERE size(tasks) > 0
  RETURN componentId, [t IN tasks | t.uid] AS task_uids
  ```

  ```cypher
  // tools/blast_radius.cypher
  MATCH (s:System {uid: $system})
  CALL algo.SSpaths({sourceNode: s, relTypes: ['CO_CHANGES'], relDirection: 'both',
                     maxLen: $depth, pathCount: 100})
  YIELD path, pathCost
  RETURN [n IN nodes(path) | n.uid] AS chain, length(path) AS depth
  ```

- **FalkorDB shown:** WCC, `SSpaths`, labels used as dynamic queues.
- **Done when:** six accepted tasks across two unrelated systems groups produce two releases,
  each with its impact list and notified owners.

### 5. Builder agent (company memory)

**Goal:** turn finished work into durable `Decision` nodes, so later agents and humans can ask
why something is the way it is.

- **Tier:** 2
- **DB user:** `citadel_builder`, read-write on `brain_<slug>` and `sim_<slug>_*`.
- **Wakes on:** `released` tasks with no `Decision` (`MADE_IN`), and merged PRs in the window
  that have a long review discussion.
- **Reads:** the task's `Action` trail, the plan and report, the linked PRs and comment
  chunks.
- **Decides:** zero to two decisions per task, each a one-line summary and rationale.
  "Nothing worth recording" is allowed.
- **Writes:** `submit_decisions` → `Decision {valid_from: now}` with `MADE_IN → Task|WorkItem`
  and `AFFECTS → System`.
- **FalkorDB shown:** semantic memory as first-class nodes linked to their sources.
- **Done when:** each released task in the sprint simulation has a decision or an explicit
  "none" episode, and every decision traces to a PR or task.

### 6. Critic agent

**Goal:** keep company memory consistent: notice when a new decision replaces or contradicts
an old one, and make the conflict visible instead of letting it silently drift.

- **Tier:** 2
- **DB user:** `citadel_critic`, read-write on `brain_<slug>` and `sim_<slug>_*`.
- **Wakes on:** decisions with no `checked_by_critic`.
- **Reads:**
  - `decisions_for_system` (new): current decisions on the same systems;
  - `decisions_as_of` (new): time-travel view.
- **Decides:** for each pair, one of supersedes, contradicts, or unrelated.
- **Writes:**
  - **supersedes:** a `SUPERSEDES` edge, and the old decision's `valid_to` is set to now;
  - **contradicts:** a `CONTRADICTS` edge, plus a new `open` task for the PM ("Resolve:
    decision X conflicts with Y"). Memory creates new work, which closes the loop.

  ```cypher
  // tools/decisions_as_of.cypher
  MATCH (d:Decision)-[:AFFECTS]->(s:System {uid: $system})
  WHERE d.valid_from <= $ts AND (d.valid_to IS NULL OR d.valid_to > $ts)
  RETURN d.uid, d.summary, d.valid_from, d.valid_to
  ```

- **FalkorDB shown:** time-bounded facts, time-travel queries, self-generated work.
- **Done when:** in the time-travel simulation, "as of" before and after the change returns
  different current decisions, and the contradiction produces a PM task.

### 7. Risk watchdog (read-only)

**Goal:** spot organisational risk in the graph before it becomes an incident: people the
company can't lose, systems only one person understands, owners who no longer do the work.

- **Tier:** 1. It's needed for the "key person leaves" and "rogue agent" simulations.
- **DB user:** `citadel_risk`, **read-only** on `brain_<slug>` and `sim_<slug>_*`, read-write
  only on `mem_<slug>_risk`. It cannot change the brain under any prompt.
- **Wakes on:** every N ticks, and right after a what-if mutation.
- **Reads:**
  - `bottleneck_people` (new, betweenness over `COLLABORATES`);
  - `single_expert_systems` (new: the top expert holds more than 70% of the recency-weighted
    activity);
  - `owners_vs_experts`;
  - `best_first_contact` (new, harmonic centrality).
- **Writes:** `Finding` nodes in its own graph `mem_<slug>_risk` only. The PM's intake job
  reads those findings and decides whether to open tasks. A finding stores the uids it cites
  as strings, because relationships can't cross graphs.
- **FalkorDB shown:** betweenness and harmonic centrality, per-graph ACL, cross-graph handoff
  through permissions rather than shared writes.
- **Done when:** in the key-person simulation, the fork lists the systems orphaned by the
  departure and the baseline does not. A write attempted as `citadel_risk` on `brain_<slug>`
  is refused by FalkorDB.

### 8. Brain agent (exists: human Q&A)

**Goal:** answer people's questions with citations and graph paths. This is the current
`brain ask` / `brain chat`.

- **Tier:** done. Extend in Tier 2 with the new read tools.
- **DB user:** `citadel_brain`, read-only on `brain_<slug>`, read-write on `agent_<slug>`
  (checkpoints).
- **Changes:** add tools that read the work layer:
  - `task_timeline` (the full `Action` trail of a task);
  - `decisions_for_system` and `decisions_as_of`;
  - `release_contents`.
  Questions like "why was #412 sent back?", "what did we believe about Auth on Oct 10?" and
  "who was told about release 3?" then all work.

---

## Optional agents (Tier 3)

### 9. Reviewer-matcher

- **Goal:** suggest human reviewers for each task, with the path that justifies them.
- **DB user:** `citadel_reviewer`, read-write on `brain_<slug>`.
- **Wakes on:** tasks entering `done`.
- **Reads:** `experts_for_system`, `path_between` (`SPpaths` from the candidate to the task's
  system), and `Person.community` for spreading review load.
- **Writes:** `SUGGESTED_REVIEWER {score, path}` edges to up to two people.
- **Replay score:** seed tasks from older real issues whose fix PR is known, and report how
  often the suggested reviewer actually reviewed that PR. This is the strongest Track 01
  evidence.

### 10. Staffing

Folded into the PM agent as described above (label propagation communities and the MaxFlow
capacity check). Make it its own role only if the PM prompt gets too large.

**Not building:** a UI designer agent. The FalkorDB repo has no UI work to ground it, so it
would be the one agent that is pure role-play.

---

## Orchestrator (`brain/sim/orchestrator.py`, not an LLM)

- **Tick loop:**
  1. Expire leases (a `lease_expired` Action is logged).
  2. Run each role in a fixed order: PM → developers → QA → PM acceptance → DevOps → Builder →
     Critic → Risk (every N ticks).
  3. Each role handles at most one task per tick.
  4. Emit the tick's actions as events for the UI.
- **Concurrency mode:** for the race simulation, run all developer instances in parallel
  threads within one tick.
- **Forks:** `fork(slug, run)` runs `GRAPH.COPY brain_<slug> sim_<slug>_<run>`, and every role
  in that run connects to the fork. `db.py` gains a run-scoped graph name, so it stays the
  single place that picks a graph.
- **Stops when:** no queue has work, a tick limit is hit, or the run is paused. It can step one
  tick at a time from the UI.
- **CLI:**

  ```bash
  brain sim run <slug> --scenario sprint --ticks 30 [--offline]
  brain sim step <run_id>
  brain sim fork <slug> --run what-if-1
  make sim SLUG=synthetic SCENARIO=race OFFLINE=1
  ```

## Permissions (one FalkorDB user per role)

| User | `brain_<slug>` | `sim_<slug>_*` | `mem_<slug>_*` | `agent_<slug>` |
|---|---|---|---|---|
| `citadel_loader` | RW | | | |
| `citadel_orchestrator` | RW | RW (creates forks) | | |
| `citadel_pm` | RW | RW | R all, RW own | |
| `citadel_dev` | RW | RW | RW own, R `qa` | |
| `citadel_qa` | RW | RW | RW own | |
| `citadel_devops` | RW | RW | RW own | |
| `citadel_builder` | RW | RW | | |
| `citadel_critic` | RW | RW | | |
| `citadel_risk` | **R** | **R** | RW own | |
| `citadel_brain` | **R** | **R** | | RW |

Created by `brain agents users <slug>` with `ACL SETUSER`, for example:

```text
ACL SETUSER citadel_risk on >${PW} +@all %R~brain_falkordb %R~sim_falkordb_* %RW~mem_falkordb_risk
```

Graph-level permissions are a newer FalkorDB feature: test them against the `falkordb:latest`
image first. Writer agents are additionally held to their own transitions by the guarded
write queries (ground rule 4), which is the second layer of defence in the rogue-agent
simulation.

## New query files

| Folder | Files |
|---|---|
| `schema/` | `constraints.cypher` |
| `derive/` | `collaborates.cypher`, `co_changes.cypher`, `system_pagerank.cypher`, `person_betweenness.cypher`, `person_communities.cypher`, `person_harmonic.cypher` |
| `work/` | `untasked_issues.cypher`, `seed_task.cypher`, `triage_task.cypher`, `reject_task.cypher`, `claim_task.cypher`, `plan_task.cypher`, `complete_task.cypher`, `claim_gate.cypher`, `qa_result.cypher`, `pm_result.cypher`, `mark_release_candidates.cypher`, `create_release.cypher`, `record_decisions.cypher`, `supersede_decision.cypher`, `contradiction.cypher`, `write_action.cypher`, `write_episode.cypher`, `expire_leases.cypher`, and one queue query per role (`queue_<role>.cypher`) |
| `tools/` | `semantic_similar_tasks`, `files_for_system`, `conflicting_tasks`, `past_regressions`, `release_trains`, `blast_radius`, `decisions_for_system`, `decisions_as_of`, `bottleneck_people`, `single_expert_systems`, `best_first_contact`, `task_timeline`, `release_contents`, `community_of` |
| `udfs/` | `citadel.js` (`decay`, `priority`); FLEX loaded from its release |

Existing tools that respect people leaving (`experts_for_system`, `person_profile`) need
`WHERE coalesce(p.active, true)` so what-if forks change their answers.

## Code layout

```
apps/backend/brain/
  agents/
    roles/       base.py, pm.py, developer.py, qa.py, devops.py, builder.py, critic.py,
                 risk.py, reviewer.py
    prompts/     pm.md, developer.md, qa.md, devops.md, builder.md, critic.md, risk.md
    policies/    offline deterministic policy per role (tests and --offline)
  sim/           orchestrator.py, scenarios.py, events.py
  memory.py      per-agent memory graph access (mem_<slug>_<role>)
  acl.py         create and check FalkorDB users
```

`agents/graph.py` keeps the router for human chat. The empty `builder` and `critic` nodes
there are replaced by the roles above.

## Simulations (one button each in the UI)

| # | Scenario | Agents | FalkorDB features it proves |
|---|---|---|---|
| 1 | **Sprint**: ten real issues go from open to released | all core | Queues, constraints, PageRank, WCC, `SSpaths`, decisions |
| 2 | **The race**: five developers compete for three tasks | Developer ×5 | Atomic writes, `UNIQUE` constraints |
| 3 | **Regression loop**: QA fails, the developer reworks, a lesson is learned | Developer, QA | Vector and full-text hybrid search, per-agent memory |
| 4 | **Key person leaves**: fork the brain, remove the top expert, compare | Risk, PM | `GRAPH.COPY`, betweenness, expertise queries |
| 5 | **Strategy A vs B**: two forks, PageRank priority vs age priority | all core | `GRAPH.COPY`, multigraph |
| 6 | **Rogue agent**: a prompt injection in an issue body | Risk, Brain, QA | ACL graph permissions, `RO_QUERY`, guarded writes |
| 7 | **Time travel**: a new decision replaces an old one, then "as of" queries | Builder, Critic, Brain | Time-bounded facts |
| 8 | **Two companies at once**: same agents on `brain_synthetic` and `brain_falkordb` | all core | Multigraph tenant isolation |

Each action card in the UI shows the feature badge, the named query that ran, and its
`GRAPH.PROFILE` output.

## Build order

| Tier | When | Scope |
|---|---|---|
| 1 | Fri night → Sat midday | Constraints, Task/Agent/Action/Episode writes, claim and leases, orchestrator, PM, Developer, QA (full-text), DevOps, Risk, derive step with PageRank, betweenness and CO_CHANGES, ACL users. Simulations 1, 2 and 6. |
| 2 | Sat | Embedding job and vector search in QA and PM, Builder, Critic, time travel, `GRAPH.COPY` forks, `citadel` UDF and FLEX conflict check, Brain's new tools, PROFILE capture. Simulations 3, 4 and 7. |
| 3 | Sun, only if ahead | Reviewer-matcher with replay score, label propagation staffing, MaxFlow, harmonic first contact, FalkorDB MCP server for an outside agent. Simulations 5 and 8. |

Every role needs a test with its offline policy and a throwaway graph (the same setup as
`tests/test_graph.py`). A simulation passes when its "done when" checks above hold.

## Implementation status

Built in two phases. **Phase 1 (agents)** is done; **phase 2 (connect to the brain)** is next.

**Phase 1: the agents and their contract** (`brain/work`, `brain/agents/roles`,
`brain/agents/policies`, `brain/agents/prompts`, `brain/sim`):

- `work/model.py`: Task, Action, Episode, Decision, Release, Finding, Lesson records and the
  status, gate and action-kind enums.
- `work/moves.py`: every legal task move (who may make it, what state it requires, what it
  sets) in one table. The in-memory store enforces it, and each `queries/work/*.cypher` guard
  must match it.
- `work/submits.py`: one pydantic model per `submit_*` tool. These are the parameter models
  of the phase 2 write queries.
- `work/store.py`: the `WorkStore` protocol: `read(name, params)` and
  `write(name, db_user, params)` on named queries, exactly like `db.run`.
  `work/memory_store.py` is the offline/test double that implements every named read and
  write in Python, with the same guards and the ACL table from `acl.py`. It is not a second
  channel: phase 2 replaces it with the FalkorDB store.
- `agents/roles/`: the nine roles (PM, developer, QA, DevOps, builder, critic, risk, brain,
  reviewer), each with jobs, a prompt, its read tools and one submit tool per job.
- `agents/runner.py`: runs one job on one subject through the brain loop (`loop.py`, now
  parameterised by prompt, submit tool and check), records the Action and the Episode.
- `agents/policies/`: a deterministic policy per job and a scripted client that plays a policy
  through the real loop, so offline runs exercise the same grounding checks as Claude.
- `sim/orchestrator.py` and `sim/scenarios.py`: the tick loop over the store, with the sprint,
  race and regression scenarios. `brain agents` lists the roles; `brain sim run <slug>
  --scenario sprint [--offline]` runs one against brain_<slug> (`make agents`, `make sim`).
  Agents read the brain through the real graph tools; offline, every role plays its policy.

**Phase 2: connect to the brain** (not built yet): the `queries/work/*.cypher` writes and
queues, `constraints.cypher`, the `derive/` step, the new `tools/` queries (role read tools
that are declared but not available yet are listed by `brain agents`), the `citadel` UDFs and
FLEX, ACL users created in FalkorDB, `GRAPH.COPY` forks, the FalkorDB store (so `brain sim`
writes the work layer into the graph), the `sim step` / `sim fork` commands, and simulations 4
to 8.
