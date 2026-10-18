"""Ask hands off to the Archivist: `ask_archivist` runs its job inline and streams its steps.

A scripted Ask (`FakeClient`) calls `ask_archivist`; the Archivist's offline policy answers the
request against the synthetic company's archive (`archive/`). Each graph test copies the
synthetic company into a temp repo root under a throwaway slug (archtest_ask_<hex>), ingests
it into brain_<slug> and deletes the graph afterwards. The ledger is a `MemoryKeeperStore`, the
checkpoints an `InMemorySaver`, the history a `MemoryChatStore`: no keeper_/agent_ graph.
"""

from __future__ import annotations

import shutil
import threading
import uuid
from typing import Any

import pytest
from agents import ask as agent
from agents.archivist import live
from agents.archivist.rules import norm
from agents.history import MemoryChatStore, Recorder
from agents.keeper.model import ArchiveRequest, archive_uid
from agents.keeper.store import MemoryKeeperStore
from agents.loop import SUBMIT
from agents.policies import offline_client
from agents.testing import (  # noqa: F401  (settings: autouse fixture)
    FakeClient,
    reply,
    settings,
    submit,
    tool_use,
)
from agents.toolset import _collect_nodes, graph_toolset, with_archivist
from agents.traces import new_trace
from agents.walk import subgraph
from brain import config, db
from brain.testing import SYNTHETIC, falkordb_up, load_company, synthetic_company, write_company
from langgraph.checkpoint.memory import InMemorySaver

ASKER = "synthetic:issue:15"  # windowed: "the decisive proof is in #900"
OLD = "synthetic:issue:900"  # archived decision: sessions -> JWT (2025-03-10)
ARCHIVE_TOOLS = {"archive_lookup", "archive_search", "archive_fetch", "submit_archive_answer"}
NOW = "2026-10-17T10:00:00Z"


@pytest.fixture
def slug(tmp_path, monkeypatch):
    """A throwaway company: the synthetic JSONL (with archive/) under a temp repo root, its
    companies/<slug>.yaml written there and brain_<slug> ingested; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    folder = tmp_path / "synthetic"
    shutil.copytree(SYNTHETIC, folder, ignore=shutil.ignore_patterns("tickets", "*.py"))
    name = f"archtest_ask_{uuid.uuid4().hex[:8]}"
    cfg = synthetic_company(name, folder=folder)
    write_company(cfg)
    db.delete_graph(name)
    load_company(cfg)
    yield name
    db.delete_graph(name)


@pytest.fixture
def store(slug):
    return MemoryKeeperStore(slug)


class Archivists:
    """The Archivist's client factory: the offline policy, counting the runs it served."""

    def __init__(self, before_call=None):
        self.made = 0
        self.before_call = before_call  # (run number, call number) -> None, before each reply

    def __call__(self):
        self.made += 1
        client = offline_client("archivist", "answer_request")
        if self.before_call is None:
            return client
        n, stream, hook = self.made, client.stream, self.before_call

        def hooked(**kw):
            hook(n, client.calls + 1)
            return stream(**kw)

        client.stream = hooked
        return client


def toolset(store, archivists=None, **kw):
    return with_archivist(graph_toolset(), lambda slug: store, archivists or Archivists(),
                          poll=0.01, **kw)  # fmt: skip


REF = {"kind": "reference", "text": OLD, "from_uid": ASKER}


def asker(params=REF, cite=(OLD,), text="In 2025, #900 decided to move to JWT [1].") -> FakeClient:
    """Ask calls ask_archivist once (reading the asking item too when it cites it), then
    answers citing `cite`."""
    look = [tool_use("t0", "get_entity", {"uid": ASKER})] if ASKER in cite else []
    return FakeClient(
        reply(*look, tool_use("t1", "ask_archivist", params)),
        reply(submit("t2", text, list(cite))),
    )


def run(slug, store, client, *, saver=None, stop=None, archivists=None, thread_id=None, **kw):
    """Every event of one Ask run (the Answer last)."""
    return list(
        agent.run_events(
            slug,
            "Why could we lean on JWTs?",
            thread_id,
            client=client,
            toolset=toolset(store, archivists, **kw),
            checkpointer=saver,
            stop=stop,
        )  # fmt: skip
    )


def archive_row(events) -> dict[str, Any]:
    [done] = [e for e in events if isinstance(e, dict) and e.get("kind") == "step_done"
              and e["tool"] == "ask_archivist"]  # fmt: skip
    assert done["error"] is None  # never an is_error result
    [row] = done["rows"]
    return row


def requests(store) -> list[ArchiveRequest]:
    rows = store.read("ledger/archive_requests", {"statuses": ["open", "running", "answered",
                                                               "failed", "refused"],
                                                  "limit": 50})  # fmt: skip
    return [ArchiveRequest(**r) for r in rows]


# --- isolation ----------------------------------------------------------------------------------


def test_inner_run_does_not_leak(slug, store):
    saver = InMemorySaver()
    events = run(slug, store, asker(), saver=saver, thread_id="th1")
    answer = events[-1]
    assert answer.text and [s.uid for s in answer.sources] == [OLD]

    # Ask's saved thread holds only Ask's messages: its question, its two calls, their results.
    config_ = {"configurable": {"thread_id": "th1"}}
    namespaces = {c.config["configurable"].get("checkpoint_ns") for c in saver.list(config_)}
    assert namespaces == {""}  # no subgraph checkpoints (an inner run would add "<node>:<id>")
    assert {c.config["configurable"].get("checkpoint_ns") for c in saver.list(None)} == {""}
    from agents.graph import build_graph

    saved = build_graph(asker(), graph_toolset(), saver).get_state(config_).values["messages"]
    uses = [b["name"] for m in saved if m["role"] == "assistant" for b in m["content"]
            if b["type"] == "tool_use"]  # fmt: skip
    assert uses == ["ask_archivist", SUBMIT]
    assert len(saved) == 5  # question, call, result, submit, its result

    # Every chunk of the inner run reached Ask's stream wrapped as an archive_step.
    dicts = [e for e in events if isinstance(e, dict)]
    assert {e["kind"] for e in dicts} == {"start", "llm", "step", "step_done", "archive_step"}
    own = [e for e in dicts if e["kind"] in ("step", "step_done")]
    assert {e["tool"] for e in own} == {"ask_archivist", SUBMIT}
    assert [e["seq"] for e in dicts if e["kind"] == "llm"] == [1, 2]
    inner = [e for e in dicts if e["kind"] == "archive_step"]
    assert {e["event"] for e in inner} == {"llm", "step", "step_done"}
    assert {e["tool"] for e in inner if e["event"] == "step_done"} >= {
        "archive_lookup", "archive_fetch", "submit_archive_answer"}  # fmt: skip


# --- the answer ---------------------------------------------------------------------------------


def test_ask_cites_archived_item_same_answer(slug, store):
    events = run(slug, store, asker())
    row = archive_row(events)
    assert row["outcome"] == "found" and row["partial"] is False and row["reason"] is None
    assert row["calls"] == 1
    [find] = row["finds"]
    assert find["uid"] == OLD and find["archived"] is True and find["verdict"] == "holds"
    assert find["date"].startswith("2025-03-10")
    assert find["title"] == "Decision: replace sessions with JWT for Auth"

    answer = events[-1]
    [source] = answer.sources
    assert source.uid == OLD and source.archived.startswith("2025-03-10")
    assert source.title == "Decision: replace sessions with JWT for Auth"
    [req] = requests(store)
    assert (req.asked_by, req.status, req.from_uid, req.refs) == ("ask", "answered", ASKER, [OLD])


def test_archive_steps_forwarded_with_parent(slug, store):
    events = run(slug, store, asker())
    inner = [e for e in events if isinstance(e, dict) and e.get("kind") == "archive_step"]
    assert inner and {e["parent"] for e in inner} == {"t1"}
    kinds = [e["event"] for e in inner]
    assert kinds[0] == "llm" and "step" in kinds and kinds[-1] == "step_done"
    fetch = next(e for e in inner if e["event"] == "step_done" and e["tool"] == "archive_fetch")
    assert fetch["count"] == 1 and fetch["error"] is None
    # Forwarded live: every archive step comes before the step_done of the call it belongs to.
    order = [e.get("kind") if isinstance(e, dict) else "answer" for e in events]
    outer_done = next(
        i for i, e in enumerate(events)
        if isinstance(e, dict) and e.get("kind") == "step_done" and e["tool"] == "ask_archivist"
    )  # fmt: skip
    assert max(i for i, k in enumerate(order) if k == "archive_step") < outer_done


def test_stop_mid_archive_marks_partial(slug, store):
    stop = threading.Event()

    def press_stop(run_n, call_n):
        if call_n == 2:  # the Archivist's second call to its model: its first tools have run
            stop.set()

    events = run(slug, store, asker(), stop=stop, archivists=Archivists(press_stop))
    row = archive_row(events)
    assert row["partial"] is True and row["reason"] == "stopped"
    [req] = requests(store)
    assert req.status == "answered" and req.partial and req.outcome == "nothing_found"
    assert events[-1].stop == "stopped"  # Ask ends at its next step, the thread kept valid


@pytest.mark.parametrize("elapsed", [36, 100])  # past the soft deadline (0.7 x 45), the hard one
def test_timeout_answers_anyway(slug, store, elapsed):
    now = [0.0]

    def later(run_n, call_n):
        now[0] = elapsed  # the clock jumps once the Archivist starts

    client = asker(cite=(ASKER,), text="The archive took too long; #15 points at #900 [1].")
    events = run(slug, store, client, archivists=Archivists(later), clock=lambda: now[0])
    row = archive_row(events)
    # Only the hard deadline is a timeout; past the soft one the run submits what it has.
    hard = elapsed > 45
    assert row["partial"] is True and row["reason"] == ("timeout" if hard else None)
    assert row["outcome"] == "nothing_found" and row["finds"] == []
    answer = events[-1]
    assert answer.text == "The archive took too long; #15 points at #900 [1]."
    assert [s.uid for s in answer.sources] == [ASKER]
    [req] = requests(store)
    assert req.status == "answered" and req.partial
    assert req.reason == ("timeout" if hard else None)  # the ledger says why, too


def test_out_of_scope_ask_still_answers(slug, store):
    params = {"kind": "reference", "text": "https://github.com/someone/else/issues/12",
              "from_uid": ASKER}  # fmt: skip
    archivists = Archivists()
    events = run(slug, store, asker(params, cite=(ASKER,), text="#15 says so [1]."),
                 archivists=archivists)  # fmt: skip
    row = archive_row(events)
    assert row["outcome"] is None and row["reason"] == "out_of_scope" and row["finds"] == []
    [req] = requests(store)
    assert req.status == "refused"
    assert events[-1].text == "#15 says so [1]."


def test_remembered_answer_returns_without_run(slug, store):
    archivists = Archivists()
    run(slug, store, asker(), archivists=archivists)
    assert archivists.made == 1
    events = run(slug, store, asker(), archivists=archivists)
    row = archive_row(events)
    assert row["reason"] == "remembered" and row["outcome"] == "found"
    assert [f["uid"] for f in row["finds"]] == [OLD]
    assert archivists.made == 1 and len(requests(store)) == 1  # no run, no new request
    assert [s.uid for s in events[-1].sources] == [OLD]


def test_archivist_that_cannot_start_ends_its_request(slug, store):
    def no_client():
        raise TypeError("Could not resolve authentication method")

    out = toolset(store, no_client).call(slug, "ask_archivist", REF)
    assert not out.is_error
    [row] = out.rows
    assert row["reason"].startswith("error: TypeError") and row["finds"] == []
    [req] = requests(store)
    assert req.status == "failed" and row["request"] == req.uid  # not left open (rule 16)


def test_live_run_takes_a_client_or_a_factory(slug, store):
    """`live.run` called directly (no Ask graph: nothing to stream to) with a client object."""
    client = offline_client("archivist", "answer_request")
    params = live.AskArchivistParams(**REF)
    [row] = live.run(slug, params, client=client, ledger=store, writer=lambda c: None, stop=None)
    assert row["outcome"] == "found" and client.calls > 0


# --- one search per question at a time (rule 16) ------------------------------------------------


class Joined(MemoryKeeperStore):
    """Notes when an open finds the question already in flight."""

    def __init__(self, slug):
        super().__init__(slug)
        self.joined = threading.Event()

    def write(self, name, db_user, params):
        rows = super().write(name, db_user, params)
        if name == "ledger/archive_open_request" and not rows[0]["created"]:
            self.joined.set()
        return rows


def test_concurrent_same_ref_runs_once(slug):
    store = Joined(slug)
    running = threading.Event()
    problems: list[str] = []  # an assert inside the hook would only end the Archivist's run

    def hold(run_n, call_n):
        if call_n == 1:
            running.set()
            if not store.joined.wait(10):  # the second asker joins before this run goes on
                problems.append("the second asker never joined")

    archivists = Archivists(hold)
    out: dict[str, list] = {}

    def ask(name):
        out[name] = run(slug, store, asker(), archivists=archivists)

    first = threading.Thread(target=ask, args=("a",))
    first.start()
    assert running.wait(10)
    second = threading.Thread(target=ask, args=("b",))
    second.start()
    first.join(30)
    second.join(30)
    assert not first.is_alive() and not second.is_alive()
    assert problems == []

    a, b = archive_row(out["a"]), archive_row(out["b"])
    assert b["calls"] == 0 and a["calls"] == 1  # the joiner caused no external calls
    assert archivists.made == 1  # one run of the Archivist
    assert a["request"] == b["request"] and len(requests(store)) == 1
    assert a["outcome"] == b["outcome"] == "found"
    assert [f["uid"] for f in a["finds"]] == [f["uid"] for f in b["finds"]] == [OLD]
    assert not [e for e in out["b"] if isinstance(e, dict) and e.get("kind") == "archive_step"]
    assert [s.uid for s in out["b"][-1].sources] == [OLD]


def _running(store, text=OLD) -> str:
    """A request another asker is running."""
    refs = [text]
    params = {"uid": archive_uid(), "kind": "reference", "text": text, "refs": refs,
              "from_uid": ASKER, "asked_by": "ask", "norm": norm("reference", text, refs),
              "now": NOW}  # fmt: skip
    [row] = store.write("ledger/archive_open_request", "citadel_brain", params)
    moved = {"uid": row["uid"], "from": ["open"], "to": "running", "now": NOW}
    assert store.write("ledger/archive_set_request", "citadel_archivist", moved)
    return row["uid"]


def _join(slug, store, **kw):
    params = live.AskArchivistParams(**REF)
    archivists = Archivists()
    [row] = live.run(slug, params, client=archivists, ledger=store, writer=lambda c: None,
                     poll=0.01, **kw)  # fmt: skip
    assert archivists.made == 0  # a joiner never runs the Archivist
    return row


def test_joiner_stopped_while_the_other_run_goes_on(slug, store):
    uid = _running(store)
    stop = threading.Event()
    stop.set()
    row = _join(slug, store, stop=stop)
    assert (row["request"], row["reason"], row["summary"]) == (uid, "stopped", live.STILL_RUNNING)
    assert row["calls"] == 0 and row["finds"] == []


def test_joiner_times_out_on_a_frozen_clock(slug, store, monkeypatch):
    """The join waits on real time, so a test clock that never moves cannot keep it waiting."""
    from brain.config import get_settings

    _running(store)
    monkeypatch.setenv("ARCHIVIST_ASK_TIMEOUT", "1")
    get_settings.cache_clear()
    done = []
    worker = threading.Thread(
        target=lambda: done.append(_join(slug, store, stop=None, clock=lambda: 0.0)), daemon=True
    )
    worker.start()
    worker.join(5)
    assert not worker.is_alive()
    [row] = done
    assert row["reason"] == "timeout" and row["summary"] == live.STILL_RUNNING


def test_joiner_says_the_run_it_joined_was_cut_short(slug, store):
    uid = _running(store)
    done = []
    worker = threading.Thread(
        target=lambda: done.append(_join(slug, store, stop=None)), daemon=True
    )
    worker.start()
    ended = {"uid": uid, "from": ["running"], "to": "answered", "outcome": "nothing_found",
             "summary": "Stopped before it reported anything.", "reason": "timeout",
             "partial": True, "calls": 2, "now": NOW}  # fmt: skip
    assert store.write("ledger/archive_set_request", "citadel_archivist", ended)
    worker.join(5)
    assert not worker.is_alive()
    [row] = done
    assert row["reason"] == "joined another question's run: timeout"
    assert row["partial"] is True and row["calls"] == 0


def test_archived_mark_survives_later_tools(slug, store):
    """A later tool that returns the archived item without the flag (related_work_items here)
    keeps the mark, in the same step, a later step and a follow-up turn."""
    from brain import tools as brain_tools

    def run_tool(slug_, name, **p):
        if name == "related_work_items":
            return [{"uid": OLD, "title": "Decision: replace sessions with JWT for Auth"}]
        return brain_tools.call(slug_, name, **p)

    base = graph_toolset()
    plain = type(base)(tools=base.tools, run=run_tool)
    tools = with_archivist(plain, lambda s: store, Archivists(), poll=0.01)
    related = {"text": "sessions JWT"}
    saver = InMemorySaver()
    first = FakeClient(
        reply(tool_use("t1", "ask_archivist", REF), tool_use("t2", "related_work_items", related)),
        reply(tool_use("t3", "related_work_items", related)),
        reply(submit("t4", "In 2025, #900 decided it [1].", [OLD])),
    )
    follow = FakeClient(
        reply(tool_use("u1", "related_work_items", related)),
        reply(submit("u2", "Still #900 [1].", [OLD])),
    )
    for client in (first, follow):
        answer = agent.ask(slug, "Why JWT?", "th_mark", client=client, toolset=tools,
                           checkpointer=saver)  # fmt: skip
        [source] = answer.sources
        assert source.uid == OLD and source.archived.startswith("2025-03-10"), client


# --- history, traces, walk ----------------------------------------------------------------------


def test_history_nests_archive_calls(slug, store):
    history = MemoryChatStore()
    rec = Recorder(history, "Why could we lean on JWTs?")
    for event in run(slug, store, asker()):
        if isinstance(event, agent.Answer):
            rec.answer(agent.answer_out(event, "tr1"), event.model)
        else:
            rec.on(dict(event))
    [thread] = [history.get_thread(t) for t in history.threads]
    [turn] = thread.turns
    assert [(s.tool, s.kind) for s in turn.steps] == [
        ("ask_archivist", "graph"), (SUBMIT, "submit")]  # fmt: skip
    outer = turn.steps[0]
    assert outer.steps and {s.kind for s in outer.steps} == {"archive"}
    assert {s.parent for s in outer.steps} == {"t1"}
    tools = [s.tool for s in outer.steps]
    assert tools[-1] == "submit_archive_answer" and "archive_fetch" in tools
    assert [s.n for s in outer.steps] == list(range(1, len(tools) + 1))
    assert turn.steps[1].steps == []


def test_trace_records_the_archive_request(slug, store):
    events = run(slug, store, asker())
    steps = [e for e in events if isinstance(e, dict) and e.get("kind") == "step_done"]
    t = new_trace(slug, "Why?", "th", via="api", steps=steps, ms=5, answer=events[-1])
    [req] = requests(store)
    assert [a.model_dump() for a in t.archive] == [
        {"request": req.uid, "outcome": "found", "calls": 1}]  # fmt: skip
    assert t.tools == ["ask_archivist"]


def test_walk_draws_finds_and_mentions_from_the_asker():
    rows = [{"request": "archive:1", "outcome": "found", "finds": [
        {"uid": OLD, "title": "Decision: JWT", "url": "https://x/900", "date": "2025-03-10",
         "verdict": "holds", "superseded_by": None, "archived": True},
        {"uid": "synthetic:doc:docs/old.md", "title": "Old auth", "url": None, "date": None,
         "verdict": "holds", "superseded_by": None, "archived": True}]}]  # fmt: skip
    nodes, rels = subgraph("ask_archivist", {"kind": "reference", "text": OLD,
                                             "from_uid": ASKER}, rows)  # fmt: skip
    by_uid = {n["uid"]: n for n in nodes}
    assert by_uid[OLD]["label"] == "WorkItem" and by_uid[OLD]["title"] == "Decision: JWT"
    assert by_uid["synthetic:doc:docs/old.md"]["label"] == "Document"
    assert by_uid[ASKER]["label"] == "WorkItem"
    # The ref names #900: that MENTIONS is stored; the doc it found on the way only implied.
    assert {(r["from"], r["to"], r["type"], r["inferred"]) for r in rels} == {
        (ASKER, OLD, "MENTIONS", False),
        (ASKER, "synthetic:doc:docs/old.md", "MENTIONS", True)}  # fmt: skip
    # "#900" and the item's url name it too; a topic request names nothing.
    for text in ("#900", "https://x/900"):
        _, rels = subgraph("ask_archivist", {"kind": "reference", "text": text,
                                             "from_uid": ASKER}, rows)  # fmt: skip
        assert {r["to"] for r in rels if not r["inferred"]} == {OLD}
    _, rels = subgraph("ask_archivist", {"kind": "topic", "text": "jwt", "from_uid": ASKER}, rows)
    assert all(r["inferred"] for r in rels)
    nodes, _ = subgraph("ask_archivist", {"kind": "topic", "text": "x",
                                          "from_uid": "system:Auth"}, rows)  # fmt: skip
    assert {n["uid"]: n["label"] for n in nodes}["system:Auth"] == "System"
    assert subgraph("ask_archivist", {"kind": "topic", "text": "x", "from_uid": None}, [])[0] == []


def test_collect_nodes_marks_archived_items_with_their_date():
    seen: dict[str, dict] = {}
    find = {"uid": OLD, "title": "Decision", "date": "2025-03-10T12:00:00Z", "archived": True}
    windowed = {"uid": ASKER, "title": "Windowed", "date": "2026-06-01", "archived": None}
    _collect_nodes([{"request": "archive:1", "finds": [find]}, windowed], seen)
    assert seen[OLD]["archived"] == "2025-03-10T12:00:00Z"
    assert "archived" not in seen[ASKER]
    assert "archive:1" not in seen  # the request is a ledger id, never cited


# --- startup recovery ---------------------------------------------------------------------------


def _open(store, text, asked_by, status):
    refs = [text]
    params = {"uid": archive_uid(), "kind": "reference", "text": text, "refs": refs,
              "asked_by": asked_by, "norm": norm("reference", text, refs), "now": NOW}  # fmt: skip
    [row] = store.write("ledger/archive_open_request", "citadel_brain", params)
    if status != "open":
        moved = {"uid": row["uid"], "from": ["open"], "to": status, "now": NOW}
        assert store.write("ledger/archive_set_request", "citadel_archivist", moved)
    return row["uid"]


def test_recover_fails_ask_requests_a_restart_cut_off():
    store = MemoryKeeperStore("synthetic")
    running = _open(store, "synthetic:issue:1", "ask", "running")
    orphan = _open(store, "synthetic:issue:2", "ask", "open")
    keeper = _open(store, "synthetic:issue:3", "keeper", "running")
    done = _open(store, "synthetic:issue:4", "ask", "answered")
    assert live.recover(store) == 2
    got = {r.uid: r for r in requests(store)}
    assert (got[running].status, got[running].reason) == ("failed", "restart")
    assert (got[orphan].status, got[orphan].reason) == ("failed", "restart")
    assert got[keeper].status == "running" and got[done].status == "answered"
    assert live.recover(store) == 0


def test_offline_chat_never_calls_the_archivist(slug, monkeypatch):
    """`agents chat --offline`: the scripted Ask lists systems and answers with the default
    Ask toolset, which holds ask_archivist; no Archivist client is ever made (no API key)."""
    from agents.offline import OfflineClient
    from agents.toolset import ask_toolset

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    made = []
    monkeypatch.setattr("agents.llm.client", lambda: made.append(1))
    tools = ask_toolset()
    assert "ask_archivist" in tools.tools
    answer = agent.ask(slug, "Which systems are there?", client=OfflineClient(), toolset=tools)
    assert answer.text and answer.text.startswith("The graph has") and made == []
