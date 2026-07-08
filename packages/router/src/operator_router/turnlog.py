from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


class TurnLog:
    """Append-only JSONL turn log. Every line carries the profile flag
    (constitution art. 4)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *, profile: str, surface: str | None, tier: int,
               latency_ms: float, input_preview: str, outcome: str) -> None:
        if not profile:
            raise ValueError("profile flag is mandatory on every log line")
        record = {
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "profile": profile,
            "surface": surface,
            "tier": tier,
            "latency_ms": round(latency_ms, 3),
            "input_preview": input_preview[:120],
            "outcome": outcome,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def lines(self) -> list[dict]:
        if not self._path.exists():
            return []
        return [json.loads(line) for line in self._path.read_text().splitlines()]
