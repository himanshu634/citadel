"""Follow-up questions through the real FalkorDB checkpointer (needs `make up`)."""

from __future__ import annotations

import uuid

import pytest
from brain import db
from brain.agents import ask as agent
from brain.config import get_settings
from langchain_falkordb.checkpoint import FalkorDBSaver
from tests.test_agent import TOOLSET, FakeClient, reply, submit, tool_use

try:
    db.ping()
except Exception:
    pytest.skip("FalkorDB is not reachable (make up)", allow_module_level=True)


@pytest.fixture
def saver_factory():
    """Fresh FalkorDBSaver instances on a throwaway graph, like two CLI runs."""
    name = f"agent_test_{uuid.uuid4().hex[:8]}"
    s = get_settings()

    def make() -> FalkorDBSaver:
        return FalkorDBSaver(
            host=s.falkordb_host,
            port=s.falkordb_port,
            username=s.falkordb_username,
            password=s.falkordb_password,
            ssl=s.falkordb_tls,
            database=name,
        )

    yield make
    if name in db.client().list_graphs():
        db.client().select_graph(name).delete()


def test_follow_up_resumes_a_thread_from_falkordb(saver_factory):
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Load [1].", ["pr:1"])),
        reply(submit("t3", "Still load [1].", ["pr:1"])),
    )
    first = agent.ask(
        "synthetic", "Why JWT?", client=client, toolset=TOOLSET, checkpointer=saver_factory()
    )
    second = agent.ask(
        "synthetic", "Sure?", first.thread_id, client=client, toolset=TOOLSET,
        checkpointer=saver_factory(),
    )  # fmt: skip
    assert second.text == "Still load [1]." and second.sources[0].title
    history = client.requests[-1]["messages"]
    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert history[1] == client.requests[1]["messages"][1]  # blocks survive the round trip
