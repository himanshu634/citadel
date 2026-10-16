"""Config diff: which saved config changes rebuild the graph or download sources again."""

from __future__ import annotations

from brain.adapters.github import GithubSource
from brain.adapters.local_docs import LocalDocsSource
from brain.config import CompanyConfig
from brain.config_diff import diff

GITHUB = GithubSource(type="github", repo="acme-labs/platform")
DOCS = LocalDocsSource(type="local_docs", path="data/inbox/acme_labs/docs")

BASE = CompanyConfig(
    slug="acme_labs",
    name="Acme Labs",
    data_permission="own",
    window={"since": "2026-04-15"},
    sources=[GITHUB.model_dump()],
)


def with_sources(cfg: CompanyConfig, sources: list) -> CompanyConfig:
    data = cfg.model_dump(mode="json")
    data["sources"] = [s.model_dump(mode="json") for s in sources]
    return CompanyConfig.model_validate(data)


def with_rules(cfg: CompanyConfig, rules: list[dict]) -> CompanyConfig:
    data = cfg.model_dump(mode="json")
    data["systems"]["rules"] = rules
    return CompanyConfig.model_validate(data)


def with_since(cfg: CompanyConfig, since: str) -> CompanyConfig:
    data = cfg.model_dump(mode="json")
    data["window"]["since"] = since
    return CompanyConfig.model_validate(data)


def test_identical_config_changes_nothing():
    d = diff(BASE, BASE)
    assert (d.changed, d.rebuild, d.refetch, d.reasons) == (False, False, [], [])


def test_name_change_needs_nothing():
    d = diff(BASE, BASE.model_copy(update={"name": "Other"}))
    assert (d.changed, d.rebuild, d.refetch) == (True, False, [])


def test_data_permission_change_needs_nothing():
    d = diff(BASE, BASE.model_copy(update={"data_permission": "public"}))
    assert (d.changed, d.rebuild, d.refetch) == (True, False, [])


def test_added_source_fetches_without_rebuild():
    d = diff(BASE, with_sources(BASE, BASE.sources + [DOCS]))
    assert (d.rebuild, d.refetch) == (False, ["local_docs:data/inbox/acme_labs/docs"])


def test_removed_source_rebuilds_from_cache():
    d = diff(with_sources(BASE, BASE.sources + [DOCS]), BASE)
    assert (d.rebuild, d.refetch) == (True, [])


def test_rules_change_rebuilds_from_cache():
    d = diff(BASE, with_rules(BASE, [{"match": "src/**", "system": "Core"}]))
    assert (d.rebuild, d.refetch) == (True, [])


def test_people_change_rebuilds_from_cache():
    data = BASE.model_dump(mode="json")
    data["people"]["bots"] = ["ci-bot"]
    d = diff(BASE, CompanyConfig.model_validate(data))
    assert (d.rebuild, d.refetch) == (True, [])


def test_since_earlier_refetches_everything():
    d = diff(BASE, with_since(BASE, "2026-01-01"))
    assert d.rebuild and d.refetch == ["github:acme-labs/platform"]


def test_since_later_rebuilds_from_cache():
    d = diff(BASE, with_since(BASE, "2026-06-01"))
    assert (d.rebuild, d.refetch) == (True, [])


def test_changed_include_refetches_that_source():
    d = diff(BASE, with_sources(BASE, [GITHUB.model_copy(update={"include": ["commits"]})]))
    assert d.rebuild and d.refetch == ["github:acme-labs/platform"]


def test_refetch_follows_new_config_order():
    old = with_sources(BASE, [DOCS])
    new = with_sources(BASE, [GITHUB, DOCS])
    d = diff(with_since(old, "2026-04-15"), with_since(new, "2026-01-01"))
    assert d.refetch == ["github:acme-labs/platform", "local_docs:data/inbox/acme_labs/docs"]


def test_reasons_are_plain_sentences():
    d = diff(BASE, with_since(with_sources(BASE, BASE.sources + [DOCS]), "2026-01-01"))
    assert d.reasons and all(r.endswith(".") and r[0].isupper() for r in d.reasons)
