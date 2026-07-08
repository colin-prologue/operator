from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class CatalogueEntry:
    """One tool-router tier entry: deterministic pattern -> operation."""

    op_name: str
    label: str  # confirmation keyword label, e.g. "move"
    pattern: re.Pattern
    readback: Callable[[re.Match], Awaitable[str]] | None
    run: Callable[[re.Match], Awaitable[str]]
    token_fetch: Callable[[re.Match], Awaitable[str | None]] | None
    # dynamic label per match, e.g. "gate voice-loop" / "kill build-box"
    # (grammar principle 2: the confirmation names the operation)
    label_for: Callable[[re.Match], str] | None = None


def match_tool(text: str, catalogue: list[CatalogueEntry]) -> tuple[CatalogueEntry, re.Match] | None:
    stripped = text.strip()
    for entry in catalogue:
        m = entry.pattern.match(stripped)
        if m:
            return entry, m
    return None
