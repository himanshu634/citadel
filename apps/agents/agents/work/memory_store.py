"""An in-memory `WorkStore`: the offline and test double of the FalkorDB store.

Why: agents, policies and the orchestrator must run with no database and no API key (ground
rule 6). This store answers every named read and write in `store.READS` / `store.WRITES` in
Python, with the same guards the Cypher will have: task moves come from `moves.MOVES`, writes
are checked against `acl.PERMISSIONS`, and one lock serialises writes the way FalkorDB
serialises write queries on a graph. It is not a second channel between agents; it stands in
for the graph until the FalkorDB store lands (phase 2).

Inputs the brain would provide (open issues, system PageRank, CO_CHANGES) are passed in.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from brain.config import graph_name

from agents import acl
from agents.graphs import mem_graph_name
from agents.work.model import (
    Action,
    ActionKind,
    Agent,
    Decision,
    Episode,
    Finding,
    Impact,
    Lesson,
    Pm,
    Qa,
    Release,
    Status,
    SuggestedReviewer,
    Task,
)
from agents.work.moves import MOVES
from agents.work.priority import task_score
from agents.work.store import READS, WRITES, Row

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "when", "from", "into", "on", "in", "of", "to", "a", "is"}


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def uid_key(uid: str) -> tuple[str, int]:
    """Sort uids by prefix, then number: task:2 before task:10."""
    prefix, _, n = uid.rpartition(":")
    return (prefix, int(n)) if n.isdigit() else (uid, 0)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


class MemoryStore:
    def __init__(
        self,
        slug: str,
        *,
        issues: Iterable[Mapping[str, Any]] = (),
        pagerank: Mapping[str, float] | None = None,
        co_changes: Iterable[tuple[str, str, float]] = (),
        graph: str | None = None,
    ) -> None:
        self.slug = slug
        self.graph = graph or graph_name(slug)  # brain_<slug>, or a sim_<slug>_<run> fork
        self.issues = [dict(i) for i in issues]  # open issues: uid, title, body, mentions
        self.pagerank = dict(pagerank or {})  # System uid -> score
        self.links: dict[str, set[str]] = defaultdict(set)  # CO_CHANGES, both directions
        for a, b, _w in co_changes:
            self.links[a].add(b)
            self.links[b].add(a)
        self.tasks: dict[str, Task] = {}
        self.agents: dict[str, Agent] = {}
        self.actions: list[Action] = []
        self.episodes: list[Episode] = []
        self.decisions: dict[str, Decision] = {}
        self.releases: dict[str, Release] = {}
        self.reviewers: list[SuggestedReviewer] = []
        self.candidates: set[str] = set()  # the :ReleaseCandidate label
        self.held: set[str] = set()  # trains DevOps held back once
        self.memory: dict[str, list[Finding | Lesson | Episode]] = defaultdict(list)  # by graph
        self._lock = threading.RLock()
        self._ids: dict[str, int] = defaultdict(int)
        self._reads: dict[str, Callable[[Mapping[str, Any]], list[Row]]] = {
            n: getattr(self, "_r_" + n.split("/", 1)[1]) for n in READS
        }
        self._writes: dict[str, Callable[[str, Mapping[str, Any]], list[Row]]] = {
            n: getattr(self, "_w_" + n.split("/", 1)[1], None) or self._move(n) for n in WRITES
        }
        self._writes["memory/write_episode"] = self._memory_episode

    # --- the WorkStore interface --------------------------------------------------------------

    def read(
        self, name: str, params: Mapping[str, Any] | None = None, *, db_user: str | None = None
    ) -> list[Row]:
        fn = self._reads.get(name)
        if fn is None:
            raise KeyError(f"no read named {name!r}")
        if db_user is not None:
            acl.check(db_user, self.slug, self._graph_for(name, db_user), "R")
        with self._lock:
            return fn(params or {})

    def write(self, name: str, db_user: str, params: Mapping[str, Any]) -> list[Row]:
        fn = self._writes.get(name)
        if fn is None:
            raise KeyError(f"no write named {name!r}")
        acl.check(db_user, self.slug, self._graph_for(name, db_user), "W")
        with self._lock:
            return fn(db_user, params)

    def _graph_for(self, name: str, db_user: str) -> str:
        if name == "memory/write_episode":  # a read-only role logs its runs in its own memory
            return mem_graph_name(self.slug, acl.ROLE_OF.get(db_user, "unknown"))
        if name in ("memory/write_lesson", "memory/lessons"):
            return mem_graph_name(self.slug, "qa")
        if name in ("memory/write_findings", "memory/findings", "work/untasked_findings"):
            return mem_graph_name(self.slug, "risk")
        return self.graph

    # --- helpers ------------------------------------------------------------------------------

    def _uid(self, prefix: str) -> str:
        self._ids[prefix] += 1
        return f"{prefix}:{self._ids[prefix]}"

    def _act(
        self,
        kind: ActionKind,
        agent: str,
        subject: str | None,
        now: int,
        summary: str,
        cites: Iterable[str] = (),
    ) -> Action:
        a = Action(
            uid=self._uid("action"),
            kind=kind,
            summary=summary,
            ts=now,
            agent=agent,
            task=subject,
            cites=list(dict.fromkeys(cites)),
        )
        self.actions.append(a)
        return a

    def _score(self, t: Task, now: int) -> float:
        return task_score(
            t.priority, self.pagerank.get(t.system or "", 0.0), t.mentions, t.created_ts, now
        )

    def _by_priority(self, tasks: Iterable[Task], now: int) -> list[Row]:
        ranked = sorted(tasks, key=lambda t: (-self._score(t, now), t.created_ts, uid_key(t.uid)))
        return [{**t.model_dump(), "score": round(self._score(t, now), 4)} for t in ranked]

    def _seed(self, now: int, **fields: Any) -> Task:
        t = Task(uid=self._uid("task"), created_ts=now, updated_ts=now, **fields)
        self.tasks[t.uid] = t
        return t

    # --- task moves (one write per entry in moves.MOVES) --------------------------------------

    def _move(self, name: str) -> Callable[[str, Mapping[str, Any]], list[Row]]:
        move = MOVES[name.removeprefix("work/")]

        def write(db_user: str, p: Mapping[str, Any]) -> list[Row]:
            task = self.tasks.get(p["task"])
            role = acl.ROLE_OF.get(db_user, "")
            if task is None or move.problem(task, role=role, agent=p["agent"], now=p["now"]):
                return []
            changes = move.changes(task, agent=p["agent"], now=p["now"], params=p)
            self.tasks[task.uid] = task.model_copy(update=changes)
            if move.name == "release_task":
                self.candidates.discard(task.uid)
            a = self._act(
                move.action,
                p["agent"],
                task.uid,
                p["now"],
                p.get("summary", ""),
                p.get("cites", ()),
            )
            return [{"task": task.uid, "action": a.uid}]

        return write

    def problem(self, name: str, db_user: str, params: Mapping[str, Any]) -> str | None:
        """Why a task move would not match (for error messages and tests), or None."""
        move = MOVES[name.removeprefix("work/")]
        task = self.tasks.get(params["task"])
        if task is None:
            return f"no task {params['task']}"
        role = acl.ROLE_OF.get(db_user, "")
        return move.problem(task, role=role, agent=params["agent"], now=params["now"])

    # --- writes -------------------------------------------------------------------------------

    def _w_register_agent(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        agent = Agent(**{k: p[k] for k in Agent.model_fields if k in p})
        self.agents[agent.uid] = agent
        return [agent.model_dump()]

    def _w_seed_task(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        """MERGE on the source: one task per issue or finding, however often it is seeded."""
        source = {k: p[k] for k in ("from_issue", "from_finding") if p.get(k)}
        if source and any(
            getattr(t, k) == v for t in self.tasks.values() for k, v in source.items()
        ):
            return []
        t = self._seed(
            p["now"],
            title=p["title"],
            body=p.get("body", ""),
            mentions=p.get("mentions", 0),
            **source,
        )
        a = self._act(
            ActionKind.SEEDED,
            p["agent"],
            t.uid,
            p["now"],
            f"Seeded: {t.title}",
            p.get("cites") or list(source.values()),
        )
        return [{"task": t.uid, "action": a.uid}]

    def _w_expire_leases(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        out = []
        for uid in list(self.tasks):
            out += self._writes["work/expire_lease"](
                db_user,
                {
                    "task": uid,
                    "agent": p["agent"],
                    "now": p["now"],
                    "summary": "Lease expired; back to the queue.",
                },
            )
        return out

    def _w_mark_release_candidates(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        new = [
            t.uid
            for t in self.tasks.values()
            if t.status == Status.DONE
            and t.qa == Qa.PASSED
            and t.pm == Pm.ACCEPTED
            and t.uid not in self.candidates
        ]
        self.candidates.update(new)
        return [{"task": uid} for uid in new]

    def _w_create_release(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        """All or nothing: every task in the train must still be releasable."""
        train = self._train(p["train"])
        if train is None:
            return []
        move, role = MOVES["release_task"], acl.ROLE_OF.get(db_user, "")
        tasks = [self.tasks[u] for u in train["task_uids"]]
        if any(move.problem(t, role=role, agent=p["agent"], now=p["now"]) for t in tasks):
            return []
        release = Release(
            uid=self._uid("release"),
            name=p["release_name"],
            ts=p["now"],
            notes=p["notes"],
            tasks=train["task_uids"],
            impacts=[Impact(**i) for i in p.get("impacts", [])],
            notify=list(dict.fromkeys(p.get("notify", []))),
        )
        self.releases[release.uid] = release
        for t in tasks:
            self.tasks[t.uid] = t.model_copy(
                update=move.changes(t, agent=p["agent"], now=p["now"], params=p)
            )
            self.candidates.discard(t.uid)
            self._act(
                ActionKind.RELEASED,
                p["agent"],
                t.uid,
                p["now"],
                f"Released in {release.name} ({release.uid})",
                [release.uid, *p.get("cites", ())],
            )
        self.held.discard(p["train"])
        return [{"release": release.uid, "tasks": release.tasks}]

    def _w_hold_train(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        train = self._train(p["train"])
        if train is None or train["held"]:  # a train is held at most once
            return []
        self.held.add(p["train"])
        a = self._act(
            ActionKind.HELD,
            p["agent"],
            p["train"],
            p["now"],
            p.get("summary", ""),
            p.get("cites", ()),
        )
        return [{"train": p["train"], "action": a.uid}]

    def _w_record_decisions(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        task = self.tasks.get(p["task"])
        if task is None or task.status != Status.RELEASED or not self._needs_decision(task.uid):
            return []
        cites = p.get("cites", ())
        if not p["decisions"]:
            a = self._act(
                ActionKind.NO_DECISION,
                p["agent"],
                task.uid,
                p["now"],
                p.get("summary") or "Nothing worth recording.",
                cites,
            )
            return [{"task": task.uid, "action": a.uid, "decisions": []}]
        made = []
        for d in p["decisions"]:
            dec = Decision(
                uid=self._uid("decision"),
                summary=d["summary"],
                rationale=d["rationale"],
                valid_from=p["now"],
                made_in=task.uid,
                systems=list(d["systems"]),
            )
            self.decisions[dec.uid] = dec
            made.append(dec.uid)
            self._act(
                ActionKind.DECISION_RECORDED,
                p["agent"],
                task.uid,
                p["now"],
                dec.summary,
                [dec.uid, *cites],
            )
        return [{"task": task.uid, "decisions": made}]

    def _w_relate_decision(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        dec = self.decisions.get(p["decision"])
        if dec is None or dec.checked_by_critic:
            return []
        now, agent, cites = p["now"], p["agent"], list(p.get("cites", ()))
        opened = []
        for r in p.get("relations", []):
            other = self.decisions.get(r["other"])
            if other is None or other.valid_to is not None or other.uid == dec.uid:
                continue
            if r["relation"] == "supersedes":
                self.decisions[other.uid] = other.model_copy(
                    update={"valid_to": now, "status": "superseded"}
                )
                dec = dec.model_copy(update={"supersedes": [*dec.supersedes, other.uid]})
                self._act(
                    ActionKind.DECISION_SUPERSEDED,
                    agent,
                    dec.uid,
                    now,
                    f"{dec.uid} supersedes {other.uid}",
                    [other.uid, *cites],
                )
            elif r["relation"] == "contradicts":
                self.decisions[other.uid] = other.model_copy(update={"status": "contested"})
                dec = dec.model_copy(
                    update={"contradicts": [*dec.contradicts, other.uid], "status": "contested"}
                )
                task = self._seed(
                    now,
                    title=f"Resolve: decision {dec.uid} conflicts with {other.uid}",
                    body=f"{dec.summary}\n\nversus\n\n{other.summary}\n\n{r.get('note', '')}",
                    system=(dec.systems or [None])[0],
                )
                opened.append(task.uid)
                self._act(
                    ActionKind.CONTRADICTION_FOUND,
                    agent,
                    task.uid,
                    now,
                    f"{dec.uid} contradicts {other.uid}",
                    [dec.uid, other.uid, *cites],
                )
        self.decisions[dec.uid] = dec.model_copy(update={"checked_by_critic": True})
        a = self._act(ActionKind.CRITIC_CHECKED, agent, dec.uid, now, p.get("summary", ""), cites)
        return [{"decision": dec.uid, "action": a.uid, "opened": opened}]

    def _w_suggest_reviewers(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        task = self.tasks.get(p["task"])
        if task is None or task.status != Status.DONE or self._suggested(task.uid):
            return []
        for r in p["reviewers"]:
            self.reviewers.append(SuggestedReviewer(task=task.uid, **r))
        a = self._act(
            ActionKind.REVIEWERS_SUGGESTED,
            p["agent"],
            task.uid,
            p["now"],
            p.get("summary", ""),
            p.get("cites", ()),
        )
        return [{"task": task.uid, "action": a.uid}]

    def _w_write_episode(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        fields = {k: p[k] for k in Episode.model_fields if k in p and k != "uid"}
        e = Episode(uid=self._uid("episode"), **fields)
        self.episodes.append(e)
        return [{"episode": e.uid}]

    def _memory_episode(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        fields = {k: p[k] for k in Episode.model_fields if k in p and k != "uid"}
        e = Episode(uid=self._uid("episode"), **fields)
        self.memory[self._graph_for("memory/write_episode", db_user)].append(e)
        return [{"episode": e.uid}]

    def _w_write_findings(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        """MERGE on (kind, subject): a risk seen again is not a new finding."""
        graph = mem_graph_name(self.slug, "risk")
        known = {(f.kind, f.subject) for f in self.memory[graph] if isinstance(f, Finding)}
        out = []
        for f in p["findings"]:
            if (f["kind"], f["subject"]) in known:
                continue
            node = Finding(uid=self._uid("finding"), ts=p["now"], **f)
            self.memory[graph].append(node)
            known.add((node.kind, node.subject))
            out.append({"finding": node.uid})
        return out

    def _w_write_lesson(self, db_user: str, p: Mapping[str, Any]) -> list[Row]:
        """MERGE on (system, regression)."""
        graph = mem_graph_name(self.slug, "qa")
        key = (p["system"], p.get("regression"))
        if any(
            (n.system, n.regression) == key for n in self.memory[graph] if isinstance(n, Lesson)
        ):
            return []
        node = Lesson(
            uid=self._uid("lesson"),
            ts=p["now"],
            **{k: p.get(k) for k in ("system", "text", "regression", "cites")},
        )
        self.memory[graph].append(node)
        return [{"lesson": node.uid}]

    # --- queue reads --------------------------------------------------------------------------

    def _r_get_task(self, p: Mapping[str, Any]) -> list[Row]:
        t = self.tasks.get(p["task"])
        return [t.model_dump()] if t else []

    def _r_get_decision(self, p: Mapping[str, Any]) -> list[Row]:
        d = self.decisions.get(p["decision"])
        return [self._decision_row(d)] if d else []

    def _r_untasked_issues(self, p: Mapping[str, Any]) -> list[Row]:
        seeded = {t.from_issue for t in self.tasks.values()}
        return [i for i in self.issues if i["uid"] not in seeded]

    def _r_untasked_findings(self, p: Mapping[str, Any]) -> list[Row]:
        seeded = {t.from_finding for t in self.tasks.values()}
        nodes = self.memory[mem_graph_name(self.slug, "risk")]
        return [f.model_dump() for f in nodes if isinstance(f, Finding) and f.uid not in seeded]

    def _r_queue_pm_triage(self, p: Mapping[str, Any]) -> list[Row]:
        return self._by_priority(
            (t for t in self.tasks.values() if t.status == Status.OPEN), p["now"]
        )

    def _r_queue_pm_accept(self, p: Mapping[str, Any]) -> list[Row]:
        tasks = (t for t in self.tasks.values() if t.status == Status.DONE and t.pm == Pm.PENDING)
        return self._by_priority(tasks, p["now"])

    def _r_queue_dev_own(self, p: Mapping[str, Any]) -> list[Row]:
        """The agent's own in-progress tasks; work sent back by a gate comes first."""
        own = [
            t
            for t in self.tasks.values()
            if t.status == Status.IN_PROGRESS and t.assignee == p["agent"]
        ]
        back = [t for t in own if t.qa == Qa.FAILED or t.pm == Pm.CHANGES_REQUESTED]
        rows = self._by_priority(back, p["now"])
        return rows + self._by_priority([t for t in own if t not in back], p["now"])

    def _r_queue_dev_claimable(self, p: Mapping[str, Any]) -> list[Row]:
        now = p["now"]
        free = (
            t
            for t in self.tasks.values()
            if t.status == Status.TRIAGED and (t.assignee is None or (t.lease_until or 0) < now)
        )
        return self._by_priority(free, now)

    def _r_queue_qa(self, p: Mapping[str, Any]) -> list[Row]:
        tasks = (t for t in self.tasks.values() if t.status == Status.DONE and t.qa == Qa.PENDING)
        return self._by_priority(tasks, p["now"])

    def _needs_decision(self, uid: str) -> bool:
        made = any(d.made_in == uid for d in self.decisions.values())
        none = any(a.kind == ActionKind.NO_DECISION and a.task == uid for a in self.actions)
        return not made and not none

    def _r_queue_builder(self, p: Mapping[str, Any]) -> list[Row]:
        done = [
            t
            for t in self.tasks.values()
            if t.status == Status.RELEASED and self._needs_decision(t.uid)
        ]
        return [t.model_dump() for t in sorted(done, key=lambda t: t.updated_ts)]

    def _r_queue_critic(self, p: Mapping[str, Any]) -> list[Row]:
        new = sorted(
            (d for d in self.decisions.values() if not d.checked_by_critic),
            key=lambda d: (d.valid_from, d.uid),
        )
        return [self._decision_row(d) for d in new]

    def _suggested(self, uid: str) -> bool:
        return any(a.kind == ActionKind.REVIEWERS_SUGGESTED and a.task == uid for a in self.actions)

    def _r_queue_reviewer(self, p: Mapping[str, Any]) -> list[Row]:
        tasks = (
            t for t in self.tasks.values() if t.status == Status.DONE and not self._suggested(t.uid)
        )
        return self._by_priority(tasks, p["now"])

    def _r_qa_failures(self, p: Mapping[str, Any]) -> list[Row]:
        """qa_failed actions on tasks about `system` that cite `regression`."""
        hits = [
            a
            for a in self.actions
            if a.kind == ActionKind.QA_FAILED
            and p["regression"] in a.cites
            and self.tasks[a.task].system == p["system"]
        ]
        return [{"action": a.uid, "task": a.task} for a in hits]

    def _r_actions(self, p: Mapping[str, Any]) -> list[Row]:
        since = p.get("since", 0)
        return [a.model_dump() for a in self.actions if a.ts >= since]

    def _r_episodes(self, p: Mapping[str, Any]) -> list[Row]:
        return [e.model_dump() for e in self.episodes]

    # --- work tools (agents.work.tools.WORK_TOOLS) ---------------------------------------------

    def _r_task_timeline(self, p: Mapping[str, Any]) -> list[Row]:
        return [a.model_dump() for a in self.actions if a.task == p["task"]]

    def _r_similar_tasks(self, p: Mapping[str, Any]) -> list[Row]:
        want = words(p["text"])
        scored = [(jaccard(want, words(t.title)), t) for t in self.tasks.values()]
        hits = [(s, t) for s, t in scored if s > 0]
        hits.sort(key=lambda st: (-st[0], st[1].created_ts, uid_key(st[1].uid)))
        return [
            {
                "uid": t.uid,
                "title": t.title,
                "status": t.status,
                "system_uid": t.system,
                "score": round(s, 3),
                "created_ts": t.created_ts,
            }
            for s, t in hits[: p.get("limit", 5)]
        ]

    def _r_conflicting_tasks(self, p: Mapping[str, Any]) -> list[Row]:
        mine = p["planned_files"]
        rows = []
        for t in self.tasks.values():
            if t.uid == p["task"] or t.status != Status.IN_PROGRESS:
                continue
            overlap = jaccard(mine, t.planned_files)
            if overlap > p.get("threshold", 0.3):
                rows.append({"uid": t.uid, "assignee": t.assignee, "overlap": round(overlap, 3)})
        return sorted(rows, key=lambda r: -r["overlap"])

    def _trains(self) -> list[Row]:
        """WCC over (:ReleaseCandidate)-[:ABOUT]->(:System): candidates sharing a system ship
        together, and trains share no systems."""
        by_system: dict[str, list[str]] = defaultdict(list)
        for uid in sorted(self.candidates, key=lambda u: int(u.split(":")[1])):
            by_system[self.tasks[uid].system or "system:none"].append(uid)
        return [
            {
                "uid": f"train:{system.removeprefix('system:')}",
                "task_uids": tasks,
                "system_uids": [system],
                "held": f"train:{system.removeprefix('system:')}" in self.held,
            }
            for system, tasks in sorted(by_system.items())
        ]

    def _train(self, uid: str) -> Row | None:
        return next((t for t in self._trains() if t["uid"] == uid), None)

    def _r_release_trains(self, p: Mapping[str, Any]) -> list[Row]:
        return self._trains()

    def _r_blast_radius(self, p: Mapping[str, Any]) -> list[Row]:
        """Shortest CO_CHANGES chains from the system, up to `depth` hops (SSpaths)."""
        start, depth = p["system"], p.get("depth", 2)
        chains = {start: [start]}
        todo = deque([start])
        while todo:
            here = todo.popleft()
            if len(chains[here]) > depth:
                continue
            for nxt in sorted(self.links.get(here, ())):
                if nxt not in chains:
                    chains[nxt] = [*chains[here], nxt]
                    todo.append(nxt)
        return [
            {"system_uid": s, "chain_uids": c, "depth": len(c) - 1}
            for s, c in chains.items()
            if s != start
        ]

    def _decision_row(self, d: Decision) -> Row:
        return {**d.model_dump(), "system_uids": d.systems}

    def _r_decisions_for_system(self, p: Mapping[str, Any]) -> list[Row]:
        current = (
            d for d in self.decisions.values() if p["system"] in d.systems and d.valid_to is None
        )
        return [self._decision_row(d) for d in sorted(current, key=lambda d: d.valid_from)]

    def _r_decisions_as_of(self, p: Mapping[str, Any]) -> list[Row]:
        ts = p["ts"]
        then = (
            d
            for d in self.decisions.values()
            if p["system"] in d.systems
            and d.valid_from <= ts
            and (d.valid_to is None or d.valid_to > ts)
        )
        return [self._decision_row(d) for d in sorted(then, key=lambda d: d.valid_from)]

    def _r_release_contents(self, p: Mapping[str, Any]) -> list[Row]:
        r = self.releases.get(p["release"])
        if r is None:
            return []
        return [{**r.model_dump(), "task_uids": r.tasks, "notify_uids": r.notify}]

    def _r_lessons(self, p: Mapping[str, Any]) -> list[Row]:
        nodes = self.memory[mem_graph_name(self.slug, "qa")]
        return [
            {**n.model_dump(), "system_uid": n.system}
            for n in nodes
            if isinstance(n, Lesson) and p.get("system") in (None, n.system)
        ]

    def _r_findings(self, p: Mapping[str, Any]) -> list[Row]:
        nodes = self.memory[mem_graph_name(self.slug, "risk")]
        return [f.model_dump() for f in nodes if isinstance(f, Finding)]
