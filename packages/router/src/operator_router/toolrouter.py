from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class CatalogueEntry:
    """One tool-router tier entry: deterministic pattern -> operation.

    `readback` may return a string starting with the sentinel "[no-arm] " to
    refuse arming entirely (e.g. the target failed to resolve): the router
    strips the sentinel and returns the remainder as the reply without
    entering AWAITING. Ordinary read-backs never start with this prefix."""

    op_name: str
    label: str  # confirmation keyword label, e.g. "move"
    pattern: re.Pattern
    readback: Callable[[re.Match], Awaitable[str]] | None
    # `run` receives the match and the token captured at read-back time
    # (None for Class R entries and entries with no token_fetch); armed
    # execution submits THIS token rather than re-reading the record, so a
    # record that moves under the read-back aborts stale (grammar spec).
    run: Callable[[re.Match, str | None], Awaitable[str]]
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
