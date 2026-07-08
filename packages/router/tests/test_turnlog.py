import json
from pathlib import Path

import pytest

from operator_router.turnlog import TurnLog


def test_append_writes_json_line_with_profile(tmp_path: Path):
    log = TurnLog(tmp_path / "logs" / "turns.jsonl")
    log.append(profile="personal", surface="proxy-pilot", tier=1,
               latency_ms=0.4, input_preview="status", outcome="ok")
    lines = log.lines()
    assert len(lines) == 1
    assert lines[0]["profile"] == "personal"
    assert lines[0]["tier"] == 1
    raw = (tmp_path / "logs" / "turns.jsonl").read_text().splitlines()
    assert json.loads(raw[0])["surface"] == "proxy-pilot"


def test_profile_is_mandatory_on_every_line(tmp_path: Path):
    log = TurnLog(tmp_path / "turns.jsonl")
    with pytest.raises(ValueError):
        log.append(profile="", surface=None, tier=3, latency_ms=1.0,
                   input_preview="x", outcome="ok")
