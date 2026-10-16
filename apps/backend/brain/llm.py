"""Claude (Anthropic API) access.

Why: one place builds the Anthropic client, the same way `db.py` is the one place that opens a
FalkorDB connection. pydantic-settings reads `.env` but does not export it to the process, so the
key from Settings is passed on explicitly; when it is unset the SDK resolves credentials itself
(ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN in the environment, or an `ant auth login` profile).
"""

from __future__ import annotations

from functools import cache
from typing import Any

import anthropic

from brain.config import get_settings

# Server-side fallback: when a safety classifier declines a request, the API re-runs it on the
# model Anthropic recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def fallback_params(model: str) -> dict[str, Any]:
    """Request params that turn on server-side fallback, or {} where the model has none.

    Claude Haiku has no server-side fallback: with `fallbacks: "default"` a declined request
    stays declined, so it is not sent. The loop reports the refusal instead.
    """
    if model.startswith("claude-haiku"):
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


@cache
def client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
