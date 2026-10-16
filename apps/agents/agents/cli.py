"""The `agents` command line.

Why: the commands that run Claude or the agent roles against a company graph (ask, chat, the
Ask traces, the role list and the simulations) live with the agents, apart from the `brain`
CLI that builds and queries the graph. Commands stay thin, like the `brain` ones, and share its
argument checks (slug, company config, FalkorDB reachable).
"""

from __future__ import annotations

import typer
from brain.cli_util import company, connected, fail, graph_name, short

from agents import checkpoint
from agents.graphs import agent_graph_name

app = typer.Typer(help="Company Brain agents: ask the graph, run the agent roles and simulations.")


@app.command()
def ask(
    slug: str,
    question: str,
    thread: str = typer.Option(None, "--thread", help="Continue an earlier conversation."),
) -> None:
    """Ask brain_<slug> a question. Claude answers from the graph, with numbered sources."""
    company(slug)
    connected()
    answer = _run_ask(slug, question, thread)
    _print_answer(answer)
    typer.secho(f"follow up with --thread {answer.thread_id}", dim=True)


@app.command("chats-backfill")
def chats_backfill(
    slug: str,
    all_threads: bool = typer.Option(
        False,
        "--all",
        help="Also threads with no trace line: offline (--offline) chats, test and eval runs.",
    ),
) -> None:
    """Write the chat history (the Ask page's chat list) for threads asked before it existed,
    from their checkpoints in agent_<slug> and data/traces/<slug>.jsonl. Only threads someone
    asked from the Ask page or `agents ask` (they have a trace line) unless --all. Safe to
    re-run."""
    from agents.backfill import backfill
    from agents.history import GraphChatStore
    from agents.traces import TraceStore

    company(slug)
    connected()
    report = backfill(
        slug,
        GraphChatStore(slug),
        checkpoint.checkpointer(slug),
        TraceStore(slug),
        traced_only=not all_threads,
    )
    typer.echo(f"{len(report.threads)} chats ({report.turns} questions) written to the history")
    if report.untraced:
        typer.echo(
            f"{len(report.untraced)} threads without a trace line left out (--all adds them)"
        )
    if report.skipped:
        typer.echo(f"skipped (no question in the checkpoint): {', '.join(report.skipped)}")


@app.command("traces")
def traces_cmd(
    slug: str,
    days: int = typer.Option(7, "--days", min=1, help="How many days back to look."),
) -> None:
    """How the brain did on live questions (CLI and Ask page): rates, latency, tokens, thumbs.
    Thumbs-down turns become draft eval cases with `make eval-drafts SLUG=<slug>`."""
    from agents.traces import TraceStore, summarize, window

    graph_name(slug)
    since, until = window(days)
    s = summarize(TraceStore(slug).read(since=since), since, until)
    typer.echo(f"{s.turns} turns in the last {days} days ({s.answered} answered)")
    if not s.turns:
        return

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.0%}"

    for name, value in s.rates.model_dump().items():
        typer.echo(f"  {name:<16} {pct(value):>5}")
    typer.echo(f"  latency ms       p50 {s.latency_ms.p50}  p95 {s.latency_ms.p95}")
    typer.echo(f"  tokens           p50 {s.tokens.p50}  p95 {s.tokens.p95}")
    typer.echo(f"  thumbs           up {s.thumbs.up}  down {s.thumbs.down}")


@app.command()
def chat(
    slug: str,
    thread: str = typer.Option(None, "--thread", help="Continue an earlier conversation."),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="One scripted turn (a list_systems call) instead of Claude: no API key needed. "
        "Checks the router, the graph tools and the checkpointer end to end.",
    ),
) -> None:
    """Talk to brain_<slug> in one thread. An empty line or Ctrl-D ends the chat."""
    company(slug)
    connected()
    if offline:
        from agents.offline import OfflineClient

        answer = _run_ask(slug, "Which systems does the graph know?", thread, OfflineClient())
        _print_answer(answer)
        typer.secho(
            f"thread {answer.thread_id} holds {answer.thread_messages} messages in "
            f"{agent_graph_name(slug)}; add a turn with --thread {answer.thread_id}",
            dim=True,
        )
        return
    typer.secho("Ask about the graph. An empty line ends the chat.", dim=True)
    while True:
        try:
            question = typer.prompt("you", default="", show_default=False)
        except typer.Abort:
            break
        if not question.strip():
            break
        answer = _run_ask(slug, question, thread)
        thread = answer.thread_id
        _print_answer(answer)
    if thread:
        typer.secho(f"continue later with --thread {thread}", dim=True)


def _run_ask(slug: str, question: str, thread: str | None, client=None):
    """One turn. A turn with the real Claude (no `client`) leaves a trace in
    data/traces/<slug>.jsonl (`agents traces`) and is kept in the chat history (agent_<slug>,
    the Ask page's chat list); a scripted --offline turn is not."""
    import time
    import uuid

    from agents import llm
    from agents.ask import Answer, answer_out, run_events
    from agents.history import GraphChatStore, Recorder
    from agents.traces import TraceStore, new_trace

    thread = thread or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    live = client is None
    recorder = Recorder(GraphChatStore(slug), question) if live else None

    def keep(**kw) -> str | None:
        if not live:
            return None
        ms = round((time.perf_counter() - started) * 1000)
        trace = new_trace(slug, question, thread, via="cli", ms=ms, **kw)
        return trace.id if TraceStore(slug).add(trace) else None

    steps: list[dict] = []
    answer = None
    try:
        for event in run_events(
            slug,
            question,
            thread_id=thread,
            client=client,
            checkpointer=checkpoint.checkpointer(slug),
        ):
            if isinstance(event, Answer):
                answer = event
                break
            if event.get("kind") == "step_done":
                steps.append(event)
            if recorder:
                recorder.on(event)
    except Exception as e:
        problem = llm.describe_error(e)
        trace_id = keep(steps=[], error=problem or f"{type(e).__name__}: {e}")
        if recorder:
            recorder.fail(problem or f"{type(e).__name__}: {e}", trace_id)
        if problem is None:
            raise
        if "No Anthropic credentials" in problem:
            problem += " Or try --offline."
        fail(problem)
    assert answer is not None  # run_events always ends with one
    trace_id = keep(steps=steps, answer=answer)
    if recorder:
        recorder.answer(answer_out(answer, trace_id), answer.model)
    return answer


def _print_answer(answer) -> None:
    if answer.text is None:
        reason = {
            "refusal": "Claude declined to answer",
            "max_tokens": "hit the output limit",
            "step_limit": "too many tool calls",
        }
        detail = (answer.stop_details or {}).get("explanation") or ""
        typer.secho(
            f"No answer: {reason.get(answer.stop, 'no answer submitted')}. {detail}", fg="yellow"
        )
    else:
        typer.echo(answer.text)
        if answer.sources:
            typer.echo("\nSources:")
            for i, src in enumerate(answer.sources, 1):
                typer.echo(f"  [{i}] {src.title or src.uid}  {src.url or src.uid}")
        if answer.path:
            typer.echo("\nPath: " + " -> ".join(p.title or p.uid for p in answer.path))
    u = answer.usage
    typer.secho(
        f"\n{answer.model} · in {u.get('input_tokens', 0)} (cache read "
        f"{u.get('cache_read_input_tokens', 0)}) · out {u.get('output_tokens', 0)}",
        dim=True,
    )


# --- roles and simulations --------------------------------------------------------------------


@app.command("agents")
def agents_cmd() -> None:
    """List the agent roles: database user, jobs (and their submit tools) and read tools."""
    from agents.roles import ROLES
    from agents.runner import missing_tools

    for role in ROLES.values():
        typer.secho(f"{role.name}  ({role.db_user})", bold=True)
        typer.echo(f"    {role.summary}")
        for job in role.jobs:
            typer.echo(f"    job {job.name} -> {job.submit.name}")
        missing = set(missing_tools(role))
        names = [t + (" (phase 2)" if t in missing else "") for t in role.read_tools]
        typer.echo(f"    reads: {', '.join(names)}")


sim_app = typer.Typer(help="Run the agents on a company: a simulated sprint, race or loop.")
app.add_typer(sim_app, name="sim")


@sim_app.command("run")
def sim_run(
    slug: str,
    scenario: str = typer.Option("sprint", "--scenario", help="sprint, race or regression."),
    ticks: int = typer.Option(30, "--ticks", help="Stop after this many ticks."),
    offline: bool = typer.Option(
        False, "--offline", help="Every role plays its deterministic policy: no API key needed."
    ),
) -> None:
    """Run a scenario. The agents read brain_<slug> through the graph tools; the work layer
    (tasks, actions, decisions) is kept in memory until the FalkorDB store lands."""
    from agents.sim import scenarios

    company(slug)
    connected()
    build = scenarios.SCENARIOS.get(scenario)
    if build is None:
        fail(f"unknown scenario {scenario!r}; known: {', '.join(scenarios.SCENARIOS)}")
    sim = build(slug, clients=scenarios.offline if offline else scenarios.online)

    def show(t) -> None:
        for a in t.actions:
            line = f"t{t.tick:<3} {a['agent']:<18} {a['kind']:<22} {a['task'] or '':<14}"
            typer.echo(f"{line} {short('summary', a['summary'], 70)}")

    sim.run(ticks, on_tick=show)
    s = sim.store
    statuses: dict[str, int] = {}
    for t in s.tasks.values():
        statuses[t.status] = statuses.get(t.status, 0) + 1
    lessons = s.read("memory/lessons", {})
    findings = s.read("memory/findings", db_user="citadel_risk")
    typer.secho(
        f"{len(sim.ticks)} ticks: tasks {statuses}, {len(s.releases)} releases, "
        f"{len(s.decisions)} decisions, {len(lessons)} lessons, {len(findings)} findings",
        bold=True,
    )


if __name__ == "__main__":
    app()
