"""Shared request dependencies.

Why: every company route is /api/companies/{slug}/..., and the slug picks a graph and a YAML
file. It is resolved here, once, and nowhere else reads it from a body, header or cookie.
"""

from __future__ import annotations

import re

from fastapi import HTTPException

from brain import config, registry


def company_slug(slug: str) -> str:
    """The path slug if it names a company file, else 404."""
    if not re.fullmatch(config.SLUG_RE, slug) or not registry.exists(slug):
        raise HTTPException(status_code=404, detail=f"No company {slug}")
    return slug
