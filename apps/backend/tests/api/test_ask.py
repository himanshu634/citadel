"""The Ask route: one question in, Server-Sent Events out (scripted Claude, fake tools)."""

from __future__ import annotations

import json
import threading

import pytest
from agents.testing import TOOLSET, FakeClient, reply, settings, submit, tool_use  # noqa: F401
from brain.api import create_app
from brain.api.ask import Asker
from fastapi.testclient import TestClient
from tests.api.conftest import write


@pytest.fixture
def company(api_root):
    write(api_root, "synthetic", name="Synthetic Co")
    return "synthetic"


def make_client(runner, claude, graph_exists=True) -> TestClient:
    asker = Asker(
        client=lambda: claude,
        toolset=lambda: TOOLSET,
        checkpointer=lambda slug: None,
        graph_exists=lambda slug: graph_exists,
    )
    return TestClient(create_app(runner, asker))


def frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_ask_streams_steps_then_the_answer(company, runner):
    claude = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
    )
    client = make_client(runner, claude)
    r = client.post(f"/api/companies/{company}/ask", json={"question": "Why JWT?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = frames(r.text)
    assert [k for k, _ in got] == ["start", "step", "step_done", "step", "step_done", "answer"]
    done = got[2][1]
    assert done["n"] == 1 and done["count"] == 2 and "kind" not in done
    assert {n["uid"] for n in done["nodes"]} == {"pr:1", "issue:11"}
    answer = got[-1][1]
    assert answer["text"] == "JWT [1]." and answer["sources"][0]["step"] == 1
    assert answer["thread_id"] == got[0][1]["thread_id"]


def test_follow_up_keeps_the_thread_id(company, runner):
    client = make_client(runner, FakeClient(reply(submit("t1", "No sources.", []))))
    r = client.post(
        f"/api/companies/{company}/ask", json={"question": "And?", "thread_id": "abc123"}
    )
    assert frames(r.text)[0] == ("start", {"thread_id": "abc123"})


def test_a_company_without_a_graph_is_refused(company, runner):
    client = make_client(runner, FakeClient(), graph_exists=False)
    r = client.post(f"/api/companies/{company}/ask", json={"question": "Why?"})
    assert r.status_code == 409 and "Build it" in r.json()["detail"]


def test_unknown_company_and_bad_bodies(company, runner):
    client = make_client(runner, FakeClient())
    assert client.post("/api/companies/nope/ask", json={"question": "x"}).status_code == 404
    assert client.post(f"/api/companies/{company}/ask", json={"question": ""}).status_code == 422
    bad_thread = {"question": "x", "thread_id": "../etc"}
    assert client.post(f"/api/companies/{company}/ask", json=bad_thread).status_code == 422


def test_a_busy_thread_is_refused(company, runner):
    asker = Asker(graph_exists=lambda slug: True, claim_wait=0.05)
    asker.claim("abc123")
    client = TestClient(create_app(runner, asker))
    r = client.post(f"/api/companies/{company}/ask", json={"question": "x", "thread_id": "abc123"})
    assert r.status_code == 409 and "still answering" in r.json()["detail"]


def test_a_follow_up_waits_for_the_stopped_run_to_let_go():
    asker = Asker(claim_wait=5)
    asker.claim("abc123")
    threading.Timer(0.05, asker.release, ["abc123"]).start()
    assert asker.claim("abc123")  # waited for the release instead of refusing


def test_missing_credentials_become_an_error_event(company, runner):
    class NoKey:
        def __init__(self):
            self.beta = self
            self.messages = self

        def stream(self, **_):
            raise TypeError('Could not resolve authentication method. Expected "api_key"')

    client = make_client(runner, NoKey())
    r = client.post(f"/api/companies/{company}/ask", json={"question": "x"})
    got = frames(r.text)
    assert got[-1] == (
        "error",
        {"detail": "No Anthropic credentials. Set ANTHROPIC_API_KEY in .env."},
    )
