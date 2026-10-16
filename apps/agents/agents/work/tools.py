"""Read tools over the work layer (tasks, actions, decisions, releases, lessons).

Why: agents choose these the same way they choose the brain's graph tools (`brain.tools`), so
each has a pydantic params model (the input schema) and a row model with uids for citations.
The store runs them by name (`tools/<name>`); phase 2 adds one `queries/tools/<name>.cypher`
per tool here, taking exactly these params.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TaskParams(_Model):
    task: str = Field(description="Task uid, e.g. 'task:3'.")


class TimelineRow(_Model):
    uid: str
    kind: str
    summary: str
    ts: int
    agent: str
    cites: list[str]


class SimilarParams(_Model):
    text: str = Field(description="Title or words to compare against existing tasks.")
    limit: int = Field(5, ge=1, le=20)


class SimilarTask(_Model):
    uid: str
    title: str
    status: str
    system_uid: str | None
    score: float  # 0..1 word overlap (phase 2: vector + full-text)
    created_ts: int


class ConflictParams(_Model):
    task: str = Field(description="Your task uid.")
    planned_files: list[str] = Field(description="The files you plan to change.")
    threshold: float = Field(0.3, ge=0, le=1, description="Minimum overlap to report.")


class Conflict(_Model):
    uid: str
    assignee: str | None
    overlap: float  # Jaccard over planned_files


class NoParams(_Model):
    pass


class Train(_Model):
    uid: str  # train:<system names>
    task_uids: list[str]
    system_uids: list[str]
    held: bool  # already held back once


class BlastParams(_Model):
    system: str = Field(description="System uid, e.g. 'system:Auth'.")
    depth: int = Field(2, ge=1, le=5, description="Maximum CO_CHANGES hops.")


class BlastRow(_Model):
    system_uid: str
    chain_uids: list[str]
    depth: int


class SystemUidParams(_Model):
    system: str = Field(description="System uid, e.g. 'system:Auth'.")


class DecisionRow(_Model):
    uid: str
    summary: str
    rationale: str
    valid_from: int
    valid_to: int | None
    status: str
    made_in: str
    system_uids: list[str]


class AsOfParams(SystemUidParams):
    ts: int = Field(description="Unix time to look at.")


class ReleaseParams(_Model):
    release: str = Field(description="Release uid, e.g. 'release:1'.")


class ReleaseRow(_Model):
    uid: str
    name: str
    notes: str
    ts: int
    task_uids: list[str]
    impacts: list[dict]
    notify_uids: list[str]


class LessonParams(_Model):
    system: str | None = Field(None, description="System uid; omit for all lessons.")


class LessonRow(_Model):
    uid: str
    system_uid: str
    text: str
    regression: str | None


@dataclass(frozen=True)
class WorkTool:
    name: str
    description: str
    params: type[_Model]
    row: type[_Model]

    @property
    def query(self) -> str:
        # Lessons live in QA's memory graph; everything else in the company graph.
        return f"memory/{self.name}" if self.name == "lessons" else f"tools/{self.name}"


WORK_TOOLS: dict[str, WorkTool] = {
    t.name: t
    for t in [
        WorkTool(
            "task_timeline",
            "A task's full Action trail: who did what and when, with what they cited.",
            TaskParams,
            TimelineRow,
        ),
        WorkTool(
            "similar_tasks",
            "Existing tasks whose titles are like the given text (to spot duplicates).",
            SimilarParams,
            SimilarTask,
        ),
        WorkTool(
            "conflicting_tasks",
            "Other in-progress tasks whose planned files overlap the given files.",
            ConflictParams,
            Conflict,
        ),
        WorkTool(
            "release_trains",
            "Accepted tasks grouped into trains that share no systems, so each ships alone.",
            NoParams,
            Train,
        ),
        WorkTool(
            "blast_radius",
            "Systems reachable from a system over co-change links, with the chain and depth.",
            BlastParams,
            BlastRow,
        ),
        WorkTool(
            "decisions_for_system",
            "Current decisions (not superseded) that affect a system.",
            SystemUidParams,
            DecisionRow,
        ),
        WorkTool(
            "decisions_as_of",
            "Decisions that were current for a system at a given time.",
            AsOfParams,
            DecisionRow,
        ),
        WorkTool(
            "release_contents",
            "One release: its tasks, impacted systems and the people it notified.",
            ReleaseParams,
            ReleaseRow,
        ),
        WorkTool(
            "lessons",
            "QA lessons: failure patterns seen twice in a system, with the regression they cite.",
            LessonParams,
            LessonRow,
        ),
    ]
}
