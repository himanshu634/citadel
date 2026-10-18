"""Claude (Anthropic API) access.

Why: one place builds the Anthropic client, the same way `db.py` is the one place that opens a
FalkorDB connection. pydantic-settings reads `.env` but does not export it to the process, so the
key from Settings is passed on explicitly; when it is unset the SDK resolves credentials itself
(ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN in the environment, or an `ant auth login` profile).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import Any

import anthropic
from brain import config
from brain.config import get_settings

from agents.mcp import McpTokenMissing

# Server-side fallback: when a safety classifier declines a request, the API re-runs it on the
# model Anthropic recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# A thinking block is bound to the system prompt, tools and messages that preceded it. A thread
# outlives a deploy that changes the prompt or the tool list, so its old blocks no longer match:
# with `drop_block` the API drops them (and every later one) instead of failing the request with
# a 400. The history itself stays append-only.
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


@dataclass(frozen=True)
class Model:
    """A Claude model the Ask page offers. `price` is the input price in USD per million tokens
    (output is 5x on all four), so the page can say how much more a model costs than Haiku."""

    id: str
    name: str
    blurb: str
    price: float
    slow: bool = False  # a turn can take minutes: the page says so before you pick it


# The only models a question may name (the Ask API rejects anything else). Cheapest first.
MODELS: tuple[Model, ...] = (
    Model("claude-haiku-5-5", "Haiku 5.5", "Fastest. Lookups and short walks.", 0.10),
    Model("claude-sonnet-5-5", "Sonnet 5.5", "Balanced. Longer walks across teams.", 2.00),
    Model("claude-opus-5-5", "Opus 5.5", "Most careful over many hops.", 4.00),
    Model("claude-fable-5-1", "Fable 5.1", "Most capable. Can take minutes.", 10.00, slow=True),
)
MODEL_IDS = frozenset(m.id for m in MODELS)


def default_model() -> str:
    """The model a question runs on when it names none: ANTHROPIC_MODEL (Sonnet 5.5 unless set)."""
    return get_settings().anthropic_model


def fallback_params(model: str) -> dict[str, Any]:
    """Request params that turn on server-side fallback, or {} where the model has none.

    Claude Haiku has no server-side fallback: with `fallbacks: "default"` a declined request
    stays declined, so it is not sent. The loop reports the refusal instead.
    """
    if model.startswith("claude-haiku"):
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


def has_api_key() -> bool:
    """A key in .env (Settings) or in the environment. The SDK may find other credentials (an
    `ant auth login` profile); the Keeper and the evals only run on a key they can see."""
    return bool(config.get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))


@cache
def client() -> anthropic.Anthropic:
    key = get_settings().anthropic_api_key
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def describe_error(exc: BaseException) -> str | None:
    """A sentence for a failed Claude call that says what to do, or None when `exc` is not one."""
    if isinstance(exc, McpTokenMissing):
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic rejected the credentials. Check ANTHROPIC_API_KEY in .env."
    if isinstance(exc, TypeError) and "authentication" in str(exc):
        # the SDK raises this when it finds no credentials at all
        return "No Anthropic credentials. Set ANTHROPIC_API_KEY in .env."
    if isinstance(exc, anthropic.APIConnectionError):
        return f"Cannot reach the Anthropic API: {exc}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    return None
