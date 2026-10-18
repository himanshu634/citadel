"""Skills: how-to guides an agent reads in its system prompt, one `<name>/SKILL.md` each.

Why: a guide (how to write Cypher for this graph) is longer than a tool description and changes
with the schema, so it lives in its own file, in the SKILL.md format (front matter with `name`
and `description`, then Markdown), and is appended to the prompt that needs it. The prompt stays
static, so its prefix stays cacheable.
"""

from __future__ import annotations

from importlib import resources


def load(name: str) -> str:
    """The body of skills/<name>/SKILL.md, without its front matter."""
    text = resources.files("agents").joinpath("skills", name, "SKILL.md").read_text()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()
