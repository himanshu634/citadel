"""DevOps policy: hold a train once when its blast radius is large; ship it with every impacted
system and the experts and declared owners to notify."""

from __future__ import annotations

from typing import Any

from brain.agents.policies.base import Call, Results, uniq

HOLD_OVER = 3  # more impacted systems than this holds the train for one tick


def release(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    train = context["train"]
    systems = train["system_uids"]
    if not results.called("list_systems"):
        return [
            ("list_systems", {}),
            *(("blast_radius", {"system": s, "depth": 2}) for s in systems),
            *(
                ("experts_for_system", {"system": s.removeprefix("system:"), "limit": 3})
                for s in systems
            ),
        ]
    known = {s["system_uid"] for s in results.rows("list_systems")}
    blast = results.rows("blast_radius")
    base = {"train": train["uid"]}
    names = " + ".join(s.removeprefix("system:") for s in systems)
    if len(blast) > HOLD_OVER and not train.get("held"):
        return {
            **base,
            "decision": "hold",
            "release_name": f"{names} (held)",
            "cites": uniq([b["system_uid"] for b in blast]),
            "notes": f"Blast radius is {len(blast)} systems; holding one tick.",
        }
    impacts = [{"system": s, "depth": 0} for s in systems if s in known]
    impacts += [{"system": b["system_uid"], "depth": b["depth"]} for b in blast]
    experts = results.rows("experts_for_system")
    notify = uniq(
        [
            *(e["person_uid"] for e in experts if e.get("is_declared_owner")),
            *(e["person_uid"] for e in experts[:1]),
        ]
    )
    notes = "\n".join(f"- {t['title']} ({t['uid']})" for t in train.get("tasks", []))
    return {
        **base,
        "decision": "ship",
        "release_name": f"{names} ({len(train['task_uids'])} tasks)",
        "notes": notes or names,
        "impacts": impacts,
        "notify": notify,
        "cites": uniq([*notify, *(i["system"] for i in impacts)]),
    }
