import subprocess
from pathlib import Path

import pytest

from operator_switchboard_mcp.storage import CorpusStore, StaleTokenError


def git_log(root: Path) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=root,
                         check=True, capture_output=True, text=True)
    return out.stdout.splitlines()


def seed_ticket(store: CorpusStore, name="cache-concurrency"):
    store.ticket_create(name, "Investigate the cache race.", lane="backlog")
    return name


def test_ticket_create_list_read(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    tickets = store.ticket_list()
    assert [t["name"] for t in tickets] == ["cache-concurrency"]
    assert store.ticket_list(lane="done") == []
    t = store.ticket_read("cache-concurrency")
    assert t["lane"] == "backlog" and t["revision"] == 0
    assert "cache race" in t["body"]


def test_transition_moves_file_and_commits_with_token_and_profile(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    result = store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    assert result == {"status": "applied", "revision": 1}
    assert store.ticket_read("cache-concurrency")["lane"] == "needs-review"
    head = git_log(corpus_root)[0]
    assert "ticket_transition" in head and "token=rev0" in head
    assert "profile=personal" in head           # goal conditions 3 + 7


def test_transition_replay_is_verified_noop(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    commits_before = len(git_log(corpus_root))
    replay = store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    assert replay["status"] == "already_applied"
    assert len(git_log(corpus_root)) == commits_before  # no second commit


def test_transition_stale_token_reports_current_revision(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    store.ticket_transition("cache-concurrency", "in-progress", "rev0")
    with pytest.raises(StaleTokenError) as exc:
        store.ticket_transition("cache-concurrency", "done", "rev99")
    assert exc.value.current_revision == 1


def test_comment_appends_feedback_block_and_commits(corpus_root):
    store = CorpusStore(corpus_root, profile="work")
    seed_ticket(store)
    store.ticket_comment("cache-concurrency", "Looks racy around evict().")
    body = store.ticket_read("cache-concurrency")["body"]
    assert "Looks racy around evict()" in body
    head = git_log(corpus_root)[0]
    assert "ticket_comment" in head and "profile=work" in head and "token=-" in head


def test_gate_stamp_exactly_once_and_decision_log(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    store.gate_create("voice-loop", state="needs-review")
    g = store.gate_read("voice-loop")
    assert g["revision"] == 0

    result = store.gate_stamp("voice-loop", "approved", "rev0")
    assert result == {"status": "applied", "revision": 1}   # goal condition 4
    assert store.gate_read("voice-loop")["state"] == "approved"
    record = corpus_root / "decisions" / "GATE-voice-loop-rev1.md"
    assert record.exists()
    assert "profile: personal" in record.read_text()

    replay = store.gate_stamp("voice-loop", "approved", "rev0")
    assert replay["status"] == "already_applied"

    with pytest.raises(StaleTokenError) as exc:
        store.gate_stamp("voice-loop", "approved", "rev0-bogus")
    assert exc.value.current_revision == 1


def test_invalid_token_shape_raises_stale_not_noop(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    for bad in ("-", "", "rev", "7", "revx"):
        with pytest.raises(StaleTokenError) as exc:
            store.ticket_transition("cache-concurrency", "done", bad)
        assert exc.value.current_revision == 0
    store.gate_create("voice-loop", state="needs-review")
    with pytest.raises(StaleTokenError):
        store.gate_stamp("voice-loop", "approved", "-")


def test_corpus_query_searches_decisions_and_corpus(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    hits = store.corpus_query("cache race")
    assert any("cache-concurrency" in h["path"] for h in hits)
