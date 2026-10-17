"""Adapter checks: what would stop the next build reading a source, found without running one."""

from __future__ import annotations

from pathlib import Path

import yaml
from brain import adapters, config, pipeline
from brain.adapters.github import client as github_client
from brain.config import CompanyConfig
from brain.testing import synthetic_company


def company(tmp_path, monkeypatch, sources: list[dict]) -> CompanyConfig:
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir(exist_ok=True)
    base = synthetic_company("acme_labs").model_dump(mode="json")
    cfg = CompanyConfig.model_validate({**base, "data_permission": "own", "sources": sources})
    path = tmp_path / "companies" / "acme_labs.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    return cfg


def test_a_missing_folder_is_skipped_not_blocking(tmp_path, monkeypatch):
    company(
        tmp_path,
        monkeypatch,
        [
            {"type": "local_docs", "path": "data/inbox/docs"},
            {"type": "canonical_jsonl", "path": "data/inbox/records"},
        ],
    )
    (tmp_path / "data/inbox/records").mkdir(parents=True)
    docs, records = pipeline.configured_sources("acme_labs")
    assert docs.key == "local_docs:data/inbox/docs" and not docs.downloads
    assert docs.problem == adapters.SourceProblem("Folder data/inbox/docs does not exist")
    assert records.problem is None


def test_downloads_without_credentials_block_the_build(tmp_path, monkeypatch):
    company(
        tmp_path,
        monkeypatch,
        [
            {"type": "github", "repo": "acme/widgets"},
            {"type": "linear", "workspace": "acme", "teams": ["ENG"]},
        ],
    )

    def no_token() -> str:
        raise github_client.GithubError("no token")

    monkeypatch.setattr(github_client, "token", no_token)
    monkeypatch.setattr(config.get_settings(), "linear_api_key", None)
    github, linear = pipeline.configured_sources("acme_labs")
    assert github.downloads and linear.downloads
    assert github.problem.blocks and "GITHUB_TOKEN" in github.problem.message
    assert linear.problem.blocks and "LINEAR_API_KEY" in linear.problem.message
    assert linear.key == "linear:acme"


def test_credentials_present_means_no_problem(tmp_path, monkeypatch):
    company(tmp_path, monkeypatch, [{"type": "github", "repo": "acme/widgets"}])
    monkeypatch.setattr(github_client, "token", lambda: "t")
    [github] = pipeline.configured_sources("acme_labs")
    assert github.problem is None


def test_paths_in_messages_stay_repo_relative(tmp_path, monkeypatch):
    company(tmp_path, monkeypatch, [{"type": "local_docs", "path": "docs"}])
    [docs] = pipeline.configured_sources("acme_labs")
    assert (
        str(tmp_path) not in docs.problem.message
        and Path("docs").as_posix() in docs.problem.message
    )
