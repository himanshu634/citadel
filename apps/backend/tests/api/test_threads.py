"""Chat history routes: the chat list, a chat reopened, delete (memory history, scripted Claude)."""

from __future__ import annotations

import pytest
from agents.history import Recorder
from agents.testing import FakeClient, reply, settings, submit, text, tool_use  # noqa: F401
from langgraph.checkpoint.memory import InMemorySaver

from .conftest import write
from .test_ask import frames, make_client


@pytest.fixture
def company(api_root):
    write(api_root, "synthetic", name="Synthetic Co")
    return "synthetic"


def ask(client, slug, question, thread_id=None):
    body = {"question": question, **({"thread_id": thread_id} if thread_id else {})}
    r = client.post(f"/api/companies/{slug}/ask", json=body)
    return dict(frames(r.text))


@pytest.fixture
def claude():
    return FakeClient(
        reply(text("Let me look."), tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
        reply(submit("t3", "Still JWT [1].", ["pr:1"])),
    )


def test_an_asked_chat_is_listed_and_reopens_with_everything(company, runner, claude):
    client = make_client(runner, claude)
    saver = InMemorySaver()  # the follow-up needs the first turn's tool results
    client.app.state.asker.checkpointer = lambda slug: saver
    first = ask(client, company, "Why JWT?")
    thread_id = first["start"]["thread_id"]
    ask(client, company, "Sure?", thread_id)

    page = client.get(f"/api/companies/{company}/threads").json()
    assert page["next"] is None
    [chat] = page["threads"]
    assert (chat["id"], chat["title"], chat["turns"], chat["last_status"]) == (
        thread_id, "Why JWT?", 2, "done")  # fmt: skip

    got = client.get(f"/api/companies/{company}/threads/{thread_id}").json()
    one, two = got["turns"]
    assert (one["question"], one["status"], one["answer"]["text"]) == ("Why JWT?", "done",
                                                                       "JWT [1].")  # fmt: skip
    assert one["answer"]["trace_id"] == first["answer"]["trace_id"]
    assert [c["text"] for c in one["calls"]] == ["Let me look.", None]
    assert [(s["tool"], s["kind"], s["call"]) for s in one["steps"]] == [
        ("related_work_items", "graph", 1), ("submit_answer", "submit", 2)]  # fmt: skip
    assert one["steps"][0]["nodes"] and one["steps"][0]["rows"]
    assert two["question"] == "Sure?" and two["answer"]["text"] == "Still JWT [1]."

    touched = client.get(f"/api/companies/{company}/refs/pr:1/threads").json()
    assert [t["id"] for t in touched] == [thread_id]
    doc = client.get(f"/api/companies/{company}/refs/doc:docs%2Fauth.md/threads")
    assert doc.status_code == 200 and doc.json() == []  # a uid with a slash still routes


def test_the_list_pages(company, runner):
    client = make_client(runner, FakeClient(*[reply(submit(f"t{i}", "x", [])) for i in range(3)]))
    ids = [ask(client, company, f"Q{i}?")["start"]["thread_id"] for i in range(3)]
    page = client.get(f"/api/companies/{company}/threads", params={"limit": 2}).json()
    assert [t["id"] for t in page["threads"]] == ids[:0:-1] and page["next"]
    rest = client.get(
        f"/api/companies/{company}/threads", params={"limit": 2, "before": page["next"]}
    ).json()
    assert [t["id"] for t in rest["threads"]] == ids[:1] and rest["next"] is None


def test_a_thumbs_shows_on_the_reopened_answer(company, runner, claude):
    client = make_client(runner, claude)
    got = ask(client, company, "Why JWT?")
    trace_id, thread_id = got["answer"]["trace_id"], got["start"]["thread_id"]
    client.post(f"/api/companies/{company}/traces/{trace_id}/feedback",
                json={"rating": "down", "note": "too short"})  # fmt: skip
    [turn] = client.get(f"/api/companies/{company}/threads/{thread_id}").json()["turns"]
    assert (turn["rating"], turn["note"]) == ("down", "too short")


def test_a_turn_no_run_will_finish_shows_as_stopped(company, runner, history):
    Recorder(history, "Cut off?").on({"kind": "start", "thread_id": "abc123"})
    client = make_client(runner, FakeClient())
    [chat] = client.get(f"/api/companies/{company}/threads").json()["threads"]
    assert chat["last_status"] == "stopped"
    [turn] = client.get(f"/api/companies/{company}/threads/abc123").json()["turns"]
    assert turn["status"] == "stopped" and "before it finished" in turn["error"]


def test_delete_removes_the_chat(company, runner, claude, history):
    deleted = []

    class Saver(InMemorySaver):
        def delete_thread(self, thread_id):
            deleted.append(thread_id)

    client = make_client(runner, claude)
    client.app.state.asker.checkpointer = lambda slug: Saver()
    thread_id = ask(client, company, "Why JWT?")["start"]["thread_id"]
    assert client.delete(f"/api/companies/{company}/threads/{thread_id}").status_code == 204
    assert deleted == [thread_id] and not history.threads
    assert client.get(f"/api/companies/{company}/threads/{thread_id}").status_code == 404
    assert client.delete(f"/api/companies/{company}/threads/{thread_id}").status_code == 404


def test_a_chat_that_is_answering_cannot_be_deleted(company, runner, history):
    Recorder(history, "Busy?").on({"kind": "start", "thread_id": "abc123"})
    client = make_client(runner, FakeClient())
    client.app.state.asker.claim("abc123")
    assert client.delete(f"/api/companies/{company}/threads/abc123").status_code == 409


def test_bad_ids_and_unknown_companies(company, runner):
    client = make_client(runner, FakeClient())
    assert client.get(f"/api/companies/{company}/threads/..%2Fx").status_code in (404, 422)
    assert client.get(f"/api/companies/{company}/threads/nope").status_code == 404
    assert client.get("/api/companies/nope/threads").status_code == 404
