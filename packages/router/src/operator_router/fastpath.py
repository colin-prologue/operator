from __future__ import annotations

import re
from dataclasses import dataclass, field

# Fast-path table v1 (kickoff spec): exact + small synonym set; no LLM.
_EXACT: dict[str, str] = {
    "stop": "stop",
    "cancel": "cancel",
    "never mind": "cancel",
    "pause": "pause",
    "resume": "resume",
    "status": "status",
    "command mode": "mode_command",
    "dictation mode": "mode_dictation",
    "work mode": "profile_work",
    "personal mode": "profile_personal",
}

_SWITCH = re.compile(r"^(?:switch to|go to)\s+(?P<name>.+)$")


@dataclass
class FastPathHit:
    intent: str
    args: dict = field(default_factory=dict)


def match_fastpath(text: str, awaiting: bool) -> FastPathHit | None:
    stripped = text.strip().lower()
    if stripped in _EXACT:
        return FastPathHit(_EXACT[stripped])
    m = _SWITCH.match(stripped)
    if m:
        return FastPathHit("switch_surface", {"name": m.group("name").strip()})
    # confirmation keywords are live only inside AWAITING (grammar principle 4)
    if awaiting and stripped.startswith("confirm"):
        return FastPathHit("confirmation", {"text": text.strip()})
    return None
