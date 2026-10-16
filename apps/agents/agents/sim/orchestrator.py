"""The orchestrator: a tick loop over the agent roles. Not an LLM.

    each tick: expire leases -> PM intake (seed tasks) -> for each step in STEPS, every agent of
    that role handles at most one subject -> the tick's Actions are its events

Why: agents never call each other. The orchestrator only decides who gets a turn and when; each
agent finds its own work through its queue read, and hands it on through its write. A step's
developers can run in parallel threads (the race scenario): the store's atomic claims decide
who gets what, exactly as FalkorDB's serial write queries would.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from agents.roles import ROLES, Ctx, Role
from agents.roles.pm import intake
from agents.runner import RunResult, run_job
from agents.toolset import Runner
from agents.work.store import Row, WorkStore

# (role, job): the fixed order of a tick. None runs the role's first job that has work.
STEPS: tuple[tuple[str, str | None], ...] = (
    ("pm", "triage"),
    ("developer", None),
    ("qa", "test"),
    ("pm", "accept"),
    ("devops", "release"),
    ("builder", "record"),
    ("critic", "check"),
    ("risk", "scan"),
    ("reviewer", "suggest"),
)
ORCHESTRATOR = Ctx("agent:orchestrator", "citadel_orchestrator", 0)
START = 1_790_000_000  # simulated clock origin (Unix seconds)
TICK_S = 60

ClientFor = Callable[[str, str], Any]  # (role, job) -> an Anthropic-shaped client


@dataclass(frozen=True)
class AgentSpec:
    uid: str  # agent:dev-1
    role: str


@dataclass
class Tick:
    tick: int
    now: int
    runs: list[RunResult] = field(default_factory=list)
    actions: list[Row] = field(default_factory=list)  # the tick's events, in order
    seeded: int = 0


class Orchestrator:
    def __init__(
        self,
        store: WorkStore,
        agents: list[AgentSpec],
        clients: ClientFor,
        *,
        graph_run: Runner | None = None,
        parallel: bool = False,
        start: int = START,
        tick_s: int = TICK_S,
        model: str = "offline-policy",
        steps: tuple[tuple[str, str | None], ...] = STEPS,
    ) -> None:
        self.store, self.agents, self.clients = store, agents, clients
        self.graph_run, self.parallel = graph_run, parallel
        self.start, self.tick_s, self.steps = start, tick_s, steps
        self.ticks: list[Tick] = []
        for a in agents:
            role = ROLES[a.role]
            store.write(
                "work/register_agent",
                ORCHESTRATOR.db_user,
                {"uid": a.uid, "role": a.role, "db_user": role.db_user, "model": model},
            )

    def _ctx(self, agent: str, db_user: str, tick: int) -> Ctx:
        return Ctx(agent, db_user, self.start + tick * self.tick_s, tick)

    def tick(self) -> Tick:
        n = len(self.ticks)
        report = Tick(n, self.start + n * self.tick_s)
        orch = self._ctx(ORCHESTRATOR.agent, ORCHESTRATOR.db_user, n)
        self.store.write("work/expire_leases", orch.db_user, {"agent": orch.agent, "now": orch.now})
        pm = next((a for a in self.agents if a.role == "pm"), None)
        if pm:
            report.seeded = len(intake(self.store, self._ctx(pm.uid, ROLES["pm"].db_user, n)))
        for role_name, job in self.steps:
            role = ROLES[role_name]
            if n % role.every:
                continue
            agents = [a for a in self.agents if a.role == role_name]
            if self.parallel and len(agents) > 1:
                with ThreadPoolExecutor(len(agents)) as pool:
                    runs = list(
                        pool.map(
                            self._turn,
                            agents,
                            [role] * len(agents),
                            [job] * len(agents),
                            [n] * len(agents),
                        )
                    )
            else:
                runs = [self._turn(a, role, job, n) for a in agents]
            report.runs += [r for r in runs if r is not None]
        report.actions = self.store.read("work/actions", {"since": report.now})
        self.ticks.append(report)
        return report

    def _turn(self, agent: AgentSpec, role: Role, job: str | None, tick: int) -> RunResult | None:
        """One agent's turn: the first subject it can claim, in its first job with work."""
        ctx = self._ctx(agent.uid, role.db_user, tick)
        for j in [role.job(job)] if job else role.jobs:
            for subject in j.queue(self.store, ctx):
                result = run_job(
                    self.store,
                    role,
                    j,
                    subject,
                    ctx,
                    client=self.clients(role.name, j.name),
                    graph_run=self.graph_run,
                )
                if result.stop != "claim_lost":
                    return result
        return None

    def idle(self, report: Tick) -> bool:
        """No queue had work: nothing ran (scans aside) and nothing is waiting to be seeded."""
        worked = any(r.role != "risk" for r in report.runs) or report.seeded or report.actions
        pending = self.store.read("work/untasked_issues") or self.store.read(
            "work/untasked_findings", db_user="citadel_pm"
        )
        return not worked and not pending

    def run(self, max_ticks: int = 50, on_tick: Callable[[Tick], None] | None = None) -> list[Tick]:
        """Tick until every queue is empty or `max_ticks` is reached."""
        for _ in range(max_ticks):
            report = self.tick()
            if on_tick:
                on_tick(report)
            if self.idle(report):
                break
        return self.ticks
