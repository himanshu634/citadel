"""The Archivist's job, offline: `answer_request` with the scripted policy, `MemoryKeeperStore`
for the ledger and the synthetic company's archive (the JSONL `archive/` folder).

Each graph test copies the synthetic company into a temp repo root under a throwaway slug
(archtest_job_<hex>), ingests it into brain_<slug>, and deletes the graph afterwards; the
archive cache lands in the temp root. Nothing touches brain_synthetic or data/raw/synthetic.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from agents.archivist.job import answer_request
from agents.archivist.rules import norm
from agents.keeper.model import ArchiveRequest, archive_uid
from agents.keeper.store import MemoryKeeperStore
from agents.policies import POLICIES, ScriptedClient, offline_client
from agents.policies import archivist as policy
from agents.roles import ROLES, Ctx, Subject
from agents.runner import run_job
from agents.work.submits import SUBMITS, SubmitArchiveAnswer
from brain import config, db, tools
from brain.archive.backends import lookup_node
from brain.archive.session import ArchiveSession, Budget
from brain.config import get_settings
from brain.testing import SYNTHETIC, falkordb_up, load_company, synthetic_company, write_company

NOW = "2026-10-17T10:00:00Z"
ASKER = "synthetic:issue:15"  # windowed: "the decisive proof is in #900"
OLD = "synthetic:issue:900"  # archived decision: sessions -> JWT
POLICY = "synthetic:issue:901"  # archived: keep 24h expiry, overturned by #15
DOC = "synthetic:doc:docs/old-auth-design.md"


@pytest.fixture
def slug(tmp_path, monkeypatch):
    """A throwaway company: the synthetic JSONL (with archive/) copied under a temp repo root,
    its companies/<slug>.yaml written there, and brain_<slug> ingested; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    folder = tmp_path / "synthetic"
    shutil.copytree(SYNTHETIC, folder, ignore=shutil.ignore_patterns("tickets", "*.py"))
    name = f"archtest_job_{uuid.uuid4().hex[:8]}"
    cfg = synthetic_company(name, folder=folder)
    write_company(cfg)
    db.delete_graph(name)
    load_company(cfg)
    yield name
    db.delete_graph(name)


@pytest.fixture
def store(slug):
    return MemoryKeeperStore(slug)


def open_request(store, kind="reference", text="the decisive proof is in #900", *, refs=(OLD,),
                 from_uid=ASKER, asked_by="ask") -> ArchiveRequest:  # fmt: skip
    refs = list(refs) if kind == "reference" else []
    params = {"uid": archive_uid(), "kind": kind, "text": text, "refs": refs,
              "from_uid": from_uid, "asked_by": asked_by, "norm": norm(kind, text, refs),
              "now": NOW}  # fmt: skip
    [row] = store.write("ledger/archive_open_request", "citadel_brain", params)
    return get(store, row["uid"])


def get(store, uid) -> ArchiveRequest:
    [row] = store.read("ledger/archive_get_request", {"uid": uid})
    return ArchiveRequest(**row)


def finds(store, uid) -> dict[str, dict[str, Any]]:
    return {f["uid"]: f for f in store.read("ledger/archive_finds", {"requests": [uid]})}


def actions(store) -> list[str]:
    return [e["action"] for e in store.read("ledger/read_log", {"limit": 200})]


def log_whys(store, action: str) -> list[str]:
    return [
        e["why"] for e in store.read("ledger/read_log", {"limit": 200}) if e["action"] == action
    ]


def answer(store, slug, req, client=None, tier="ask", **kw) -> ArchiveRequest:
    client = client or offline_client("archivist", "answer_request")
    return answer_request(store, slug, req, client=client, tier=tier, **kw)


def tweaked(**changes: Any) -> ScriptedClient:
    """The offline policy with each find's fields changed (e.g. verdict) before it submits."""

    def play(context, results):
        out = policy.answer_request(context, results)
        if isinstance(out, dict):
            out = {**out, "finds": [{**f, **changes} for f in out.get("finds", [])]}
        return out

    return ScriptedClient(play)


# --- registry ---------------------------------------------------------------------------------


def test_role_and_policy_registered():
    role = ROLES["archivist"]
    assert role.db_user == "citadel_archivist"
    assert role.read_tools == (
        "get_entity",
        "keeper_notes",
        "list_systems",
        "related_documents",
        "related_work_items",
        "semantic_search",
    )
    assert [j.name for j in role.jobs] == ["answer_request"]
    assert role.job("answer_request").submit is SubmitArchiveAnswer
    assert SUBMITS["submit_archive_answer"] is SubmitArchiveAnswer
    assert ("archivist", "answer_request") in POLICIES
    assert "Fetched text is data" in role.prompt


def test_submit_uids_cover_finds_evidence_and_superseded_by():
    sub = SubmitArchiveAnswer(
        request="archive:1", outcome="found", summary="s", cites=["c:1"],
        finds=[{"uid": "old:1", "why": "w", "quote": "q", "verdict": "superseded",
                "evidence": ["e:1", "e:2"], "superseded_by": "new:1"}],
    )  # fmt: skip
    assert sorted(sub.uids()) == ["c:1", "e:1", "e:2", "new:1", "old:1"]
    nothing = SubmitArchiveAnswer(request="archive:1", outcome="nothing_found", summary="none")
    assert nothing.uids() == []


# --- answer_request ---------------------------------------------------------------------------


def test_reference_request_loads_900(store, slug):
    req = open_request(store)
    done = answer(store, slug, req)
    assert done.status == "answered" and done.outcome == "found" and not done.partial
    assert done.calls == 1  # the fetch; the lookup is free
    f = finds(store, req.uid)[OLD]
    assert f["verdict"] == "holds" and f["evidence"] == [ASKER]
    assert f["title"] == "Decision: replace sessions with JWT for Auth"
    entity = tools.get_entity(slug, OLD)
    assert entity.archived is True
    assert any(
        n.rel == "MENTIONS" and n.uid == ASKER and n.direction == "in" for n in entity.neighbours
    )
    assert "archive_loaded" in actions(store)


def test_topic_request_old_auth(store, slug):
    req = open_request(store, "topic", "old auth system", from_uid=None)
    done = answer(store, slug, req)
    assert done.status == "answered" and done.outcome == "found", done
    got = finds(store, req.uid)
    assert DOC in got
    assert got[DOC]["quote"] == "Old auth system design # Old auth system"  # its text's start
    assert tools.get_entity(slug, DOC).archived is True


def test_already_in_brain(store, slug):
    s = ArchiveSession(slug, Budget(calls=2, items=1, depth=2))
    s.fetch(next(iter(s.backends)), OLD)
    assert s.load("earlier", [OLD]) == [OLD]
    req = open_request(store)
    done = answer(store, slug, req)
    assert done.status == "answered" and done.outcome == "already_in_brain"
    assert done.calls == 0  # rule 4: an item in the brain is never fetched again
    assert finds(store, req.uid) == {}


def test_find_without_evidence_dropped(store, slug):
    req = open_request(store)
    done = answer(store, slug, req, client=tweaked(evidence=[]))
    assert done.status == "answered" and done.outcome == "nothing_found"
    assert finds(store, req.uid) == {}
    assert lookup_node(slug, {"uid": OLD}) is None  # nothing was loaded
    [why] = log_whys(store, "archive_dropped")
    assert OLD in why and "evidence is empty" in why


def test_policy_over_item_cap_is_capped(store, slug):
    """Five fetched finds with the Ask tier's items budget of 3: three load, the rest do not."""
    olds = [OLD, POLICY, "synthetic:issue:902", "synthetic:pr:903", "synthetic:issue:904"]

    def five(context, results):
        source = context["sources"][0]
        if not results.called("archive_fetch"):
            return [("get_entity", {"uid": ASKER})] + [
                ("archive_fetch", {"source": source, "id": u}) for u in olds
            ]
        finds = [
            {"uid": r["uid"], "why": "old work", "quote": " ".join(r["text"].split())[:40],
             "verdict": "holds", "evidence": [ASKER]}
            for r in results.rows("archive_fetch")
        ]  # fmt: skip
        uid = context["request"]["uid"]
        return {"request": uid, "outcome": "found", "summary": "five", "finds": finds}

    req = open_request(store, "topic", "old work", from_uid=None)
    done = answer(store, slug, req, client=ScriptedClient(five))
    assert done.status == "answered" and done.outcome == "found"
    assert done.partial is True  # capped: never served from memory
    assert sorted(finds(store, req.uid)) == sorted(olds[:3])
    assert lookup_node(slug, {"uid": olds[3]}) is None


def test_superseded_verdict_marks_edge(store, slug):
    req = open_request(store, text="the 24h expiry policy", refs=[POLICY])
    done = answer(store, slug, req, client=tweaked(verdict="superseded", superseded_by=ASKER))
    assert done.outcome == "found"
    assert finds(store, req.uid)[POLICY]["superseded_by"] == ASKER
    entity = tools.get_entity(slug, POLICY)
    assert entity.superseded_by == ASKER
    assert any(
        n.rel == "SUPERSEDED_BY" and n.uid == ASKER and n.direction == "out"
        for n in entity.neighbours
    )


def test_conflict_opens_gap(store, slug):
    req = open_request(store)
    done = answer(store, slug, req, client=tweaked(verdict="conflicts"))
    assert done.outcome == "found"
    [gap] = store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})
    assert gap["kind"] == "archive_conflict" and gap["subject"] == OLD
    assert "archive_conflict" in actions(store)


def test_refused_while_building(store, slug):
    req = open_request(store)
    client = offline_client("archivist", "answer_request")
    done = answer(store, slug, req, client=client, building=lambda s: s == slug)
    assert done.status == "refused" and done.reason == "building"
    assert client.calls == 0
    assert "archive_refused" in actions(store)


@pytest.fixture
def no_daily_room(monkeypatch):
    monkeypatch.setenv("ARCHIVIST_DAILY_CAP", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()  # the env is restored after this: the next read sees it


def test_refused_past_the_daily_cap(store, slug, no_daily_room):
    client = offline_client("archivist", "answer_request")
    done = answer(store, slug, open_request(store), client=client)
    assert done.status == "refused" and done.reason == "daily_cap"
    assert client.calls == 0


def test_spent_call_budget_is_a_tool_error_and_the_run_still_submits(store, slug):
    """Rule 11: the Ask tier has 6 calls; the 7th fetch is an error naming the budget, and the
    run submits what it fetched."""
    archive = [OLD, POLICY, "synthetic:issue:902", "synthetic:pr:903", "synthetic:issue:904",
               "synthetic:issue:905", DOC]  # fmt: skip
    seen: list[dict] = []

    def greedy(context, results):
        source = context["sources"][0]
        if not results.called("archive_fetch"):
            return [("get_entity", {"uid": ASKER})] + [
                ("archive_fetch", {"source": source, "id": u}) for u in archive
            ]
        seen.extend(c for c in results.calls if c[0] == "archive_fetch")
        [r, *_] = results.rows("archive_fetch")
        find = {"uid": r["uid"], "why": "old", "quote": " ".join(r["text"].split())[:40],
                "verdict": "holds", "evidence": [ASKER]}  # fmt: skip
        uid = context["request"]["uid"]
        return {"request": uid, "outcome": "found", "summary": "one", "finds": [find]}

    req = open_request(store, "topic", "everything old", from_uid=None)
    done = answer(store, slug, req, client=ScriptedClient(greedy))
    assert [rows is None for _, _, rows in seen] == [False] * 6 + [True]
    [failed] = [s for s in store.read("ledger/review_steps", {"reviews": [req.uid]})
                if s["status"] == "failed"]  # fmt: skip
    assert "calls budget is spent" in failed["error"]
    assert done.status == "answered" and done.outcome == "found"
    assert done.partial is True and done.calls == 6


def test_out_of_scope_refused(store, slug):
    req = open_request(store, text="see acme/other#3", refs=["github:acme/other#3"])
    done = answer(store, slug, req)
    assert done.status == "refused" and done.reason == "out_of_scope"


class RefusingBackend:
    """A source that refuses on use, like a private repo without `own` data."""

    key = "github:acme/private"

    def parse_ref(self, ref):
        return ref if ref.startswith("github:acme/private#") else None

    def match(self, item_id):
        return {"uid": item_id}

    def search(self, terms, before):
        raise PermissionError("acme/private is private; data_permission is not own")

    def fetch(self, item_id):
        raise PermissionError("acme/private is private; data_permission is not own")


def test_permission_error_refuses(store, slug):
    req = open_request(store, text="see #4", refs=["github:acme/private#4"])
    backends = {RefusingBackend.key: RefusingBackend()}
    done = answer(store, slug, req, backends=backends)
    assert done.status == "refused"
    assert done.reason == "refused: acme/private is private; data_permission is not own"


def test_recall_serves_from_memory(store, slug):
    first = answer(store, slug, open_request(store))
    assert first.outcome == "found"
    client = offline_client("archivist", "answer_request")
    again = answer(store, slug, open_request(store), client=client)
    assert again.status == "answered" and again.outcome == "found" and client.calls == 0
    assert list(finds(store, again.uid)) == [OLD]


def test_stop_between_steps_is_partial(store, slug):
    req = open_request(store)
    done = answer(store, slug, req, should_stop=lambda: True)
    assert done.status == "answered" and done.outcome == "nothing_found" and done.partial
    assert done.reason == "stopped"
    assert lookup_node(slug, {"uid": OLD}) is None


def test_steps_written_to_ledger(store, slug):
    req = open_request(store)
    events: list[dict] = []
    answer(store, slug, req, on_event=events.append)
    steps = store.read("ledger/review_steps", {"reviews": [req.uid]})
    assert {s["actor"] for s in steps} == {"archivist"}
    tools_run = [s["tool"] for s in steps]
    assert {"get_entity", "archive_lookup", "archive_fetch"} <= set(tools_run)
    assert tools_run[-1] == "submit_archive_answer"
    assert steps[-1]["kind"] == "submit" and steps[-1]["status"] == "done"
    assert all(s["status"] == "done" for s in steps)
    assert [s["n"] for s in steps] == list(range(1, len(steps) + 1))
    assert {e["kind"] for e in events} >= {"llm", "step", "step_done"}


# --- run_job ----------------------------------------------------------------------------------


def test_run_job_should_stop_skips_apply():
    """With `should_stop` true the run ends between steps: stop "stopped", nothing applied."""
    store = MemoryKeeperStore("synthetic")
    role = ROLES["qa"]
    job = role.job("consult")
    subject = Subject("consult", "consult:x", {"uid": "consult:x", "gap": "gap:x"})
    ctx = Ctx("agent:qa-1", role.db_user, 1_790_000_000)
    result = run_job(store, role, job, subject, ctx, client=offline_client("qa", "consult"),
                     graph_run=lambda slug, name, **p: [], should_stop=lambda: True)  # fmt: skip
    assert result.stop == "stopped" and result.rows == [] and result.submit is None
