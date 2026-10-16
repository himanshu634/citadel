"""Company registry: companies/*.yaml listing, validation, atomic writes, comment-keeping edits."""

from __future__ import annotations

import shutil

import pytest
from backend import registry
from brain import config
from brain.testing import synthetic_company

REPO = config.REPO_ROOT

VALID_DRAFT = {
    "slug": "acme_labs",
    "name": "Acme",
    "data_permission": "own",
    "window": {"since": "2026-04-15"},
    "sources": [{"type": "github", "repo": "acme/widgets"}],
}


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


def test_render_then_load_round_trips(tmp_root):
    cfg = synthetic_company("acme_labs")
    registry.write_new(cfg)
    assert config.load_company("acme_labs") == cfg
    text = (tmp_root / "companies" / "acme_labs.yaml").read_text()
    keys = [line.split(":")[0] for line in text.splitlines() if line and not line.startswith(" ")]
    assert keys == ["slug", "name", "data_permission", "window", "sources", "systems", "people"]


def test_write_new_refuses_existing(tmp_root):
    registry.write_new(synthetic_company("acme_labs"))
    with pytest.raises(FileExistsError):
        registry.write_new(synthetic_company("acme_labs"))


def test_update_keeps_comments(tmp_root):
    shutil.copy(REPO / "companies" / "falkordb.yaml", tmp_root / "companies" / "falkordb.yaml")
    cfg = registry.read("falkordb")
    registry.update("falkordb", cfg.model_copy(update={"name": "FalkorDB Inc"}))
    text = (tmp_root / "companies" / "falkordb.yaml").read_text()
    assert "# how file paths map to System nodes" in text
    assert "name: FalkorDB Inc" in text
    assert registry.read("falkordb").name == "FalkorDB Inc"


def test_validate_draft_reports_source_field_paths():
    draft = {
        "slug": "acme_labs",
        "name": "Acme",
        "data_permission": "own",
        "window": {"since": "2026-04-15"},
        "sources": [{"type": "github", "repo": "not a repo"}],
    }
    cfg, errors = registry.validate_draft(draft)
    assert cfg is None
    assert [e.loc for e in errors] == [["sources", 0, "repo"]]


def test_validate_draft_slug_error_path():
    _, errors = registry.validate_draft({**VALID_DRAFT, "slug": "Acme-Labs"})
    assert ["slug"] in [e.loc for e in errors]


def test_list_companies_keeps_going_past_a_broken_file(tmp_root):
    registry.write_new(synthetic_company("acme_labs"))
    (tmp_root / "companies" / "broken.yaml").write_text("slug: broken\nname: [\n")
    out = registry.list_companies()
    assert [c.slug for c in out] == ["acme_labs", "broken"]
    assert isinstance(out[1], registry.InvalidCompany)


HANDBOOK = {"name": "handbook", "url": "https://handbook.example/mcp", "token_env": "HB_TOKEN"}


def test_mcp_servers_survive_a_settings_save_and_leave_when_removed(tmp_root):
    path = tmp_root / "companies" / "acme_labs.yaml"
    registry.write_new(synthetic_company("acme_labs"))
    assert "mcp_servers" not in path.read_text()  # optional: not written when empty

    cfg = registry.read("acme_labs")
    registry.update(
        "acme_labs", cfg.model_copy(update={"mcp_servers": [config.McpServer(**HANDBOOK)]})
    )
    saved = registry.read("acme_labs")
    assert [s.name for s in saved.mcp_servers] == ["handbook"]

    # The Settings page gets the config as JSON and saves it back unchanged.
    sent_back = config.CompanyConfig.model_validate(saved.model_dump(mode="json"))
    registry.update("acme_labs", sent_back.model_copy(update={"name": "Acme Inc"}))
    assert registry.read("acme_labs").mcp_servers == saved.mcp_servers
    assert "HB_TOKEN" in path.read_text() and "secret" not in path.read_text()

    registry.update("acme_labs", sent_back.model_copy(update={"mcp_servers": []}))
    assert "mcp_servers" not in path.read_text()
