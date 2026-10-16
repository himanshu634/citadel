"""The Keeper's graph name, who may use it, and its budget settings."""

import pytest
from agents import acl
from agents.graphs import keeper_graph_name
from brain.config import Settings


def test_keeper_graph_name():
    assert keeper_graph_name("synthetic") == "keeper_synthetic"
    with pytest.raises(ValueError):
        keeper_graph_name("Bad Slug")


def test_keeper_permissions():
    g = keeper_graph_name("acme")
    assert acl.kind_of("acme", g) == "keeper"
    assert acl.can("citadel_keeper", "acme", g, "W")
    assert acl.can("citadel_keeper", "acme", "brain_acme", "W")
    assert acl.can("citadel_pm", "acme", g, "W") and acl.can("citadel_qa", "acme", g, "W")
    assert acl.can("citadel_brain", "acme", g, "W")  # Ask opens gaps
    assert not acl.can("citadel_risk", "acme", g, "W")
    assert acl.PERMISSIONS["citadel_keeper"] == {"brain": acl.RW, "keeper": acl.RW}
    assert acl.ROLE_OF["citadel_keeper"] == "keeper"


def test_keeper_setuser_commands():
    passwords = {user: "pw" for user in acl.PERMISSIONS}
    lines = acl.setuser_commands("acme", passwords)
    keeper = next(line for line in lines if " citadel_keeper " in line)
    assert "%RW~keeper_acme" in keeper and "%RW~brain_acme" in keeper


def test_keeper_settings_defaults():
    s = Settings()
    assert (s.keeper_budget, s.keeper_build_budget, s.keeper_notice_cap) == (5, 3, 10)
