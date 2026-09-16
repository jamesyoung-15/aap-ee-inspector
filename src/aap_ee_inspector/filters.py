"""Shared name-matching helpers for exclusion/inclusion filtering."""

from __future__ import annotations

import fnmatch


def matches_any(name: str, patterns: list[str]) -> bool:
    """Return True if `name` matches any of the given fnmatch glob patterns."""
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def parse_csv_patterns(value: str | None) -> list[str] | None:
    """Split a comma-separated CLI argument into a list of trimmed patterns.

    Returns None if `value` is None (i.e. the flag wasn't provided), which
    callers should treat as "no filter applied".
    """
    if value is None:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]
