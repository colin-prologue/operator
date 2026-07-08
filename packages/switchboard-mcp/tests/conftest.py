import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    """A throwaway git repo with the corpus layout. Never the real repo."""
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path
