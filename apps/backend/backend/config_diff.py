"""What a saved config change requires.

Why: the Settings save route must tell the user, before anything runs, whether the change needs
a graph rebuild and which sources must be downloaded again. Only the rules below touch the
graph; renaming a company or changing its data permission does not. A rebuild reads the cache,
so it costs no API calls; a source only needs a new download when the cache lacks its data (a
new or changed source, or a window that now starts earlier).
"""

from __future__ import annotations

from brain.adapters import REGISTRY
from brain.config import CompanyConfig, SourceConfig
from pydantic import BaseModel


class ConfigDiff(BaseModel):
    changed: bool  # any difference at all, including name and data_permission
    rebuild: bool  # the graph must be reset and loaded again from the cache
    refetch: list[str] = []  # adapter keys to download again, in the new config's order
    reasons: list[str] = []  # plain sentences for the save dialog


def _by_key(config: CompanyConfig) -> dict[str, SourceConfig]:
    return {REGISTRY[s.type].key(s): s for s in config.sources}


def diff(old: CompanyConfig, new: CompanyConfig) -> ConfigDiff:
    old_sources, new_sources = _by_key(old), _by_key(new)
    reasons: list[str] = []
    rebuild = False
    refetch: set[str] = set()

    since_earlier = new.window.since < old.window.since
    if new.window.since != old.window.since:
        rebuild = True
        if since_earlier:
            refetch.update(new_sources)
            reasons.append(
                f"The time window now starts earlier ({new.window.since}), so every source is "
                "downloaded again and the graph is rebuilt."
            )
        else:
            reasons.append(
                f"The time window now starts later ({new.window.since}), so the graph is "
                "rebuilt from the data already downloaded."
            )

    for key in old_sources.keys() - new_sources.keys():
        rebuild = True
        reasons.append(f"Source {key} was removed, so the graph is rebuilt without it.")

    for key, source in new_sources.items():
        if key not in old_sources:
            refetch.add(key)
            reasons.append(f"Source {key} was added and will be downloaded.")
        elif source.model_dump() != old_sources[key].model_dump():
            rebuild = True
            refetch.add(key)
            reasons.append(f"Source {key} changed, so it is downloaded again.")

    if new.systems != old.systems:
        rebuild = True
        reasons.append("The system rules changed, so the graph is rebuilt from the cache.")
    if new.people != old.people:
        rebuild = True
        reasons.append("The people settings changed, so the graph is rebuilt from the cache.")

    return ConfigDiff(
        changed=old.model_dump() != new.model_dump(),
        rebuild=rebuild,
        refetch=[key for key in new_sources if key in refetch],
        reasons=reasons,
    )
