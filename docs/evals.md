# Evals: how reliable is the brain agent?

`make test` proves the agent loop's mechanics with a scripted client. It cannot say whether a
real model picks the right graph tools and cites the right nodes. The evals do: they ask Claude
fixed questions against a loaded company graph and grade every answer with deterministic checks.
No model grades another model.

## Results (2026-10-17)

Baseline: **Claude Haiku 5.5** (`claude-haiku-5-5`), effort `medium`, the shipped default.
Comparison: **Claude Sonnet 5.5** (`claude-sonnet-5-5`), effort `medium`. Every case, `REPEAT=3`,
both companies, all four runs on the same graphs (no sync or rebuild in between). The agent,
its prompt and its tools are the code of `3fdc2eb` in all four; the later commits a file names
(`86bc0e5`, `45ac124`) changed only the eval harness (the commit in the meta line, this report).

The tables below are generated, not typed:
`make eval-report FILES="docs/evals/synthetic/*haiku* docs/evals/synthetic/*sonnet* docs/evals/falkordb/*haiku* docs/evals/falkordb/*sonnet*"`.
Δ is the change in pass rate from the baseline, in percentage points. With `REPEAT=3` one run
is 33 points of one case: read the tag and total rows, not single cases.

In short: the agent answers 88–96% of runs fully right on both companies with either model, and
no run errored. Sonnet's lower pass rate is not wrong answers: every one of its 11 failed runs
named the right people or systems but cited a coarser node than the case asks for (see
[Known misses](#known-misses)). Sonnet uses fewer tool calls and half the output tokens.

| Company | Cases | haiku-5-5 medium | sonnet-5-5 medium | Δ |
|---|---:|---:|---:|---:|
| synthetic | 17 | 48/51 (94%) | 45/51 (88%) | -6 pt |
| falkordb | 23 | 66/69 (96%) | 64/69 (93%) | -3 pt |

### synthetic

- `20261017T150153Z-claude-haiku-5-5-medium.jsonl`: claude-haiku-5-5, effort medium, REPEAT 3, commit 3fdc2eb, started 2026-10-17T15:00:32+00:00
- `20261017T173243Z-claude-sonnet-5-5-medium.jsonl`: claude-sonnet-5-5, effort medium, REPEAT 3, commit 45ac124, started 2026-10-17T17:31:32+00:00

| Tag | Cases | haiku-5-5 medium | sonnet-5-5 medium | Δ |
|---|---:|---:|---:|---:|
| experts | 3 | 8/9 (89%) | 3/9 (33%) | -56 pt |
| ownership | 1 | 3/3 (100%) | 3/3 (100%) | = |
| impact | 1 | 3/3 (100%) | 3/3 (100%) | = |
| history | 4 | 12/12 (100%) | 12/12 (100%) | = |
| naming | 1 | 3/3 (100%) | 3/3 (100%) | = |
| abstain | 2 | 6/6 (100%) | 6/6 (100%) | = |
| thread | 1 | 3/3 (100%) | 3/3 (100%) | = |
| semantic | 3 | 7/9 (78%) | 9/9 (100%) | +22 pt |
| interview | 1 | 3/3 (100%) | 3/3 (100%) | = |
| **all** | 17 | **48/51 (94%)** | **45/51 (88%)** | **-6 pt** |

| Per run | haiku-5-5 medium | sonnet-5-5 medium |
|---|---:|---:|
| cases passed every run | 14/17 | 14/17 |
| runs that errored (API or graph) | 0 | 0 |
| graph tool calls | 3.2 | 2.2 |
| seconds | 6.3 | 5.4 |
| input tokens (cached) | 24,941 (19,376) | 20,104 (15,741) |
| output tokens | 777 | 382 |

| Case | Tag | haiku-5-5 medium | sonnet-5-5 medium | Δ |
|---|---|---:|---:|---:|
| `auth-expert` | experts | 2/3 | 2/3 | = |
| `billing-reviewer` | experts | 3/3 | 0/3 | -100 pt |
| `infra-expert-not-bot` | experts | 3/3 | 1/3 | -67 pt |
| `web-owners-vs-experts` | ownership | 3/3 | 3/3 | = |
| `billing-impact` | impact | 3/3 | 3/3 | = |
| `jwt-why-and-who` | history | 3/3 | 3/3 | = |
| `duplicate-invoices` | history | 3/3 | 3/3 | = |
| `managed-postgres-decision` | history | 3/3 | 3/3 | = |
| `checkout-ownership-open` | history | 3/3 | 3/3 | = |
| `login-code-loose-name` | naming | 3/3 | 3/3 | = |
| `no-such-system` | abstain | 3/3 | 3/3 | = |
| `no-such-person` | abstain | 3/3 | 3/3 | = |
| `checkout-follow-up` | thread | 3/3 | 3/3 | = |
| `semantic-login-state` | semantic | 3/3 | 3/3 | = |
| `semantic-overcharge` | semantic | 2/3 | 3/3 | +33 pt |
| `semantic-own-database` | semantic | 2/3 | 3/3 | +33 pt |
| `interview-asks` | interview | 3/3 | 3/3 | = |

Failed runs:

- `auth-expert` #1 (haiku-5-5 medium): turn 1 cite_any: none of ['person:alice'] (cited system:Auth)
- `auth-expert` #0 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:alice'] (cited system:Auth)
- `billing-reviewer` #0 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:bob', 'person:erin'] (cited system:Billing)
- `billing-reviewer` #1 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:bob', 'person:erin'] (cited system:Billing)
- `billing-reviewer` #2 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:bob', 'person:erin'] (cited system:Billing)
- `infra-expert-not-bot` #1 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:dave'] (cited system:Infra)
- `infra-expert-not-bot` #2 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:dave'] (cited system:Infra)
- `semantic-overcharge` #1 (haiku-5-5 medium): turn 1 tools_any: none of ['semantic_search']
- `semantic-own-database` #1 (haiku-5-5 medium): turn 1 max_steps: 6/5

### falkordb

- `20261017T150454Z-claude-haiku-5-5-medium.jsonl`: claude-haiku-5-5, effort medium, REPEAT 3, commit 86bc0e5, started 2026-10-17T15:02:33+00:00
- `20261017T173458Z-claude-sonnet-5-5-medium.jsonl`: claude-sonnet-5-5, effort medium, REPEAT 3, commit 45ac124, started 2026-10-17T17:32:57+00:00

| Tag | Cases | haiku-5-5 medium | sonnet-5-5 medium | Δ |
|---|---:|---:|---:|---:|
| experts | 3 | 8/9 (89%) | 9/9 (100%) | +11 pt |
| ownership | 1 | 3/3 (100%) | 3/3 (100%) | = |
| impact | 2 | 6/6 (100%) | 3/6 (50%) | -50 pt |
| history | 3 | 9/9 (100%) | 9/9 (100%) | = |
| semantic | 4 | 11/12 (92%) | 12/12 (100%) | +8 pt |
| docs | 2 | 6/6 (100%) | 6/6 (100%) | = |
| people | 3 | 8/9 (89%) | 7/9 (78%) | -11 pt |
| aggregate | 1 | 3/3 (100%) | 3/3 (100%) | = |
| abstain | 2 | 6/6 (100%) | 6/6 (100%) | = |
| chat | 1 | 3/3 (100%) | 3/3 (100%) | = |
| interview | 1 | 3/3 (100%) | 3/3 (100%) | = |
| **all** | 23 | **66/69 (96%)** | **64/69 (93%)** | **-3 pt** |

| Per run | haiku-5-5 medium | sonnet-5-5 medium |
|---|---:|---:|
| cases passed every run | 20/23 | 21/23 |
| runs that errored (API or graph) | 0 | 0 |
| graph tool calls | 3.3 | 2.2 |
| seconds | 8.0 | 7.0 |
| input tokens (cached) | 34,539 (24,336) | 27,670 (21,204) |
| output tokens | 1,202 | 606 |

| Case | Tag | haiku-5-5 medium | sonnet-5-5 medium | Δ |
|---|---|---:|---:|---:|
| `query-execution-expert` | experts | 3/3 | 3/3 | = |
| `ci-expert-not-bot` | experts | 2/3 | 3/3 | +33 pt |
| `commands-reviewer` | experts | 3/3 | 3/3 | = |
| `declared-owners-vs-workers` | ownership | 3/3 | 3/3 | = |
| `query-execution-impact` | impact | 3/3 | 0/3 | -100 pt |
| `rdb-serialization-loose-name` | impact | 3/3 | 3/3 | = |
| `unique-constraint-regression` | history | 3/3 | 3/3 | = |
| `parenthesised-where` | history | 3/3 | 3/3 | = |
| `batch-backport-missed-prs` | history | 3/3 | 3/3 | = |
| `semantic-uniqueness-slowdown` | semantic | 3/3 | 3/3 | = |
| `semantic-container-privileges` | semantic | 2/3 | 3/3 | +33 pt |
| `semantic-slow-log-crash` | semantic | 3/3 | 3/3 | = |
| `semantic-huge-knn` | semantic | 3/3 | 3/3 | = |
| `project-about` | docs | 3/3 | 3/3 | = |
| `how-to-profile` | docs | 3/3 | 3/3 | = |
| `headcount` | people | 3/3 | 3/3 | = |
| `no-real-names` | people | 2/3 | 3/3 | +33 pt |
| `closest-collaborators` | people | 3/3 | 1/3 | -67 pt |
| `most-issues-module` | aggregate | 3/3 | 3/3 | = |
| `no-such-system` | abstain | 3/3 | 3/3 | = |
| `no-such-person` | abstain | 3/3 | 3/3 | = |
| `greeting` | chat | 3/3 | 3/3 | = |
| `interview-asks` | interview | 3/3 | 3/3 | = |

Failed runs:

- `ci-expert-not-bot` #0 (haiku-5-5 medium): turn 1 cite_any: none of ['person:dvirdukhan', 'person:aviavni'] (cited system:CI, system:build/runtime)
- `closest-collaborators` #0 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:aviavni', 'person:dvirdukhan'] (cited github:FalkorDB/FalkorDB:pr:3063, github:FalkorDB/FalkorDB:pr:3346, github:FalkorDB/FalkorDB:pr:3342, github:FalkorDB/FalkorDB:pr:2489, github:FalkorDB/FalkorDB:pr:2488)
- `closest-collaborators` #2 (sonnet-5-5 medium): turn 1 cite_any: none of ['person:aviavni', 'person:dvirdukhan'] (cited github:FalkorDB/FalkorDB:pr:3063, github:FalkorDB/FalkorDB:pr:3346, github:FalkorDB/FalkorDB:pr:3342, github:FalkorDB/FalkorDB:pr:2487, github:FalkorDB/FalkorDB:pr:2489)
- `no-real-names` #2 (haiku-5-5 medium): turn 1 answered: expected answered=True; turn 2 answered: expected answered=True
- `query-execution-impact` #0 (sonnet-5-5 medium): turn 1 cite_any: none of ['system:tests/flow', 'system:src/arithmetic'] (cited system:Query execution)
- `query-execution-impact` #1 (sonnet-5-5 medium): turn 1 cite_any: none of ['system:tests/flow', 'system:src/arithmetic'] (cited system:Query execution)
- `query-execution-impact` #2 (sonnet-5-5 medium): turn 1 cite_any: none of ['system:tests/flow', 'system:src/arithmetic'] (cited system:Query execution)
- `semantic-container-privileges` #0 (haiku-5-5 medium): turn 1 max_steps: 9/6

## Known misses

None of these is a case bug: in every failed run the check failed on what the agent actually
did, and no case was changed to pass. 17 failed runs (Haiku 6, Sonnet 11), by cause:

- **Right answer, citation one level too coarse** (13 runs: all 11 of Sonnet's, 2 of Haiku's).
  The agent names the right people or systems in the text but cites only the node the question
  was about, or the evidence behind it: `system:Billing` instead of `person:bob` / `person:erin`,
  `system:Query execution` instead of the systems coupled to it, the PRs behind a collaboration
  instead of the two people. The graders count citations because a citation is what makes an
  answer checkable (the Ask page links each one), so these stay failures. It is the main
  difference between the two models: Sonnet answers in fewer tool calls (2.2 vs 3.2 per run)
  with half the output tokens, and more often hangs every claim on one source; Haiku cites each
  ranked row. Telling the agent in `agents/system_prompt.md` to cite the rows a ranking names, not
  only its subject, is the likely fix. It is not made here, so the baseline measures the shipped
  prompt.
- **Too many steps** (2 runs, Haiku), both with right answers: `semantic-container-privileges`
  ran `related_work_items` three times in other wordings before `semantic_search` (9 tool calls,
  limit 6); `semantic-own-database` found the answer with `semantic_search` on its third call,
  then looked up three entities with `get_entity` (6 calls, limit 5).
- **Skipped semantic search** (1 run, Haiku): `semantic-overcharge` answered from full-text hits
  alone; the case expects `semantic_search`, because the question shares no words with the issue.
- **No answer** (1 run, Haiku): in `no-real-names` #2 Haiku called `submit_answer` with markers
  `[1]`..`[5]` and an empty `sources` list eight times; each was refused with the reason, and the
  turn ended without an answer. The follow-up turn did the same.

No run errored (API or graph) in any of the four files. The Keeper ledgers (`keeper_synthetic`,
`keeper_falkordb`) held the same gaps and claims before and after the runs: the `interview` cases
read open gaps and file nothing.

## Method

- **Cases.** Each company has a case file in
  [`apps/agents/agents/evals/cases/`](../apps/agents/agents/evals/cases/):
  `synthetic.yaml` (17 cases on the offline synthetic company, fixed answers) and
  `falkordb.yaml` (23 cases on the public [FalkorDB/FalkorDB](https://github.com/FalkorDB/FalkorDB)
  repo, several taken word for word from questions people asked on the Ask page). A case is one
  question, or a short conversation whose follow-ups share one thread. Each case says why it
  exists (`why:`).
- **Checks** ([`graders.py`](../apps/agents/agents/evals/graders.py)), per turn, all pure:
  - `answered`: the answer came through `submit_answer` (or, for a case that expects no answer,
    did not).
  - `cite_any` / `cite_all` / `cite_none`: which graph uids the answer cites in its sources or
    path. The loop already refuses any uid that no tool returned, so a citation is always real;
    these checks say whether it is the *right* one.
  - `tools_any` / `tools_all` / `tools_none`: which named graph tools ran (a call that returned an
    error does not count as having run).
  - `text_any` / `text_all` / `text_none` / `text_re`: case-insensitive substrings or a regex
    in the answer text.
  - `max_steps`: at most this many graph tool calls in the turn.
- **Gold refs.** On the live repo, rankings change with every sync, so an expected uid is often
  not a literal but a gold ref: "the top 2 `person_uid`s that `experts_for_system(system=CI)`
  returns", read from the graph when the run starts. The tools themselves are tested against
  known graphs in `apps/brain/tests/`, so here they count as ground truth. Literal uids are kept
  for facts that cannot change: who wrote a merged PR, which issue it closed, bot logins.
- **Pass.** A run passes when every check of every turn passes. Each case runs `REPEAT` times
  (models are not deterministic), so a case reports a pass rate, not a verdict.
- **Errors.** A run that raised (an API overload, a graph error) fails, but is counted apart
  from graded failures in the tables, so an outage is never published as an agent miss.
- **Noise.** With `REPEAT=3`, one run is 33 points of a case's pass rate. A change on a single
  case is noise; read the tag and total rows.

## Rerun

```bash
make eval SLUG=synthetic REPEAT=3                         # baseline: the default model and effort
make eval SLUG=synthetic REPEAT=3 MODEL=claude-sonnet-5-5 BASELINE=data/evals/synthetic/<baseline>.jsonl
make eval-report FILES="data/evals/synthetic/<baseline>.jsonl data/evals/synthetic/<other>.jsonl"
```

`SLUG=falkordb` needs `brain_falkordb` synced and its chunks embedded (`make sync SLUG=falkordb`,
which embeds). Results go to `data/evals/<slug>/<utc time>-<model>-<effort>.jsonl`: a `meta`
line (model, effort, repeat, commit, cases), then one line per run with every turn's checks,
answer text, cited uids, tools, tokens and latency. `make eval-report` turns result files into
the tables on this page ([`report.py`](../apps/agents/agents/evals/report.py)); per company the
first file is the baseline. The files behind this page are in [`docs/evals/`](evals/).
