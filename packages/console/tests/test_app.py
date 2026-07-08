import io
import subprocess
from pathlib import Path

import pytest

from operator_console.app import run_console
from operator_switchboard_mcp.storage import CorpusStore


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


async def test_repl_survives_a_tool_error_and_keeps_going(corpus_root):
    """A tool-level exception (e.g. reading a ticket the server reports as
    unknown, which the client code then indexes into as if it succeeded)
    must not kill the REPL: it prints an error and the loop continues."""
    CorpusStore(corpus_root, profile="personal").ticket_create(
        "cache-concurrency", "Investigate the cache race.")
    stdin = io.StringIO("read ticket ghost\nlist tickets\nexit\n")
    stdout = io.StringIO()

    await run_console(corpus_root, "personal", no_llm=True,
                      stdin=stdin, stdout=stdout)

    out = stdout.getvalue()
    assert "error:" in out.lower()
    assert "cache-concurrency" in out   # the REPL kept going after the error
