"""Phase 0 acceptance — one test per kickoff-spec goal condition."""

import json
import subprocess

import pytest

from operator_router.turnlog import TurnLog


def turn_lines(root):
    return TurnLog(root / "logs" / "turns.jsonl").lines()


async def test_gc1_register_two_kinds_and_resolve(bench):
    r = bench["router"]
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("register chat proxy-pilot at claude://claude.ai/chat/abc")
    await r.handle("confirm register")
    reg = bench["registry"]
    assert reg.resolve("build-box").surface.kind == "tmux"
    assert reg.resolve("proxy pilot").surface.kind == "chat"  # fuzzy spoken


async def test_gc2_switch_is_fastpath_zero_llm(bench):
    r = bench["router"]
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("switch to build-box")
    assert bench["llm"].calls == []
    line = turn_lines(bench["root"])[-1]
    assert line["tier"] == 1


async def test_gc3_ticket_flow_with_commit_trail(bench):
    r = bench["router"]
    assert "cache-concurrency" in await r.handle("list tickets")
    assert "cache race" in await r.handle("read ticket cache-concurrency")
    await r.handle("comment on cache-concurrency: needs a lock audit")
    await r.handle("confirm comment")
    await r.handle("move cache-concurrency to needs-review")
    await r.handle("confirm move")
    t = await bench["bridge"].call("ticket_read", {"name": "cache-concurrency"})
    assert t["lane"] == "needs-review"
    log = subprocess.run(["git", "log", "--format=%s"], cwd=bench["root"],
                         capture_output=True, text=True, check=True).stdout
    assert "ticket_transition" in log and "token=rev" in log
    assert "profile=personal" in log


async def test_gc4_gate_stamp_idempotency(bench):
    r = bench["router"]
    await r.handle("stamp gate voice-loop as approved")
    reply = await r.handle("confirm gate voice-loop")
    assert "revision 1" in reply
    # replay the same token directly against the tool: verified no-op
    replay = await bench["bridge"].call(
        "gate_stamp", {"name": "voice-loop", "state": "approved",
                       "token": "rev0"})
    assert replay["status"] == "already_applied"
    stale = await bench["bridge"].call(
        "gate_stamp", {"name": "voice-loop", "state": "approved",
                       "token": "rev99"})
    assert stale["status"] == "stale_token" and stale["current_revision"] == 1


async def test_gc5_unmatched_reaches_tier3(bench):
    r = bench["router"]
    reply = await r.handle("what changed in the repo overnight?")
    assert reply == "(tier 3 reached)"
    assert turn_lines(bench["root"])[-1]["tier"] == 3


@pytest.mark.skip(reason="goal condition 6 is a manual smoke test against "
                         "Claude Desktop: uv run python "
                         "packages/desktop-adapter/smoke.py")
def test_gc6_desktop_adapter_smoke():
    ...


async def test_gc7_profile_flag_on_every_line_and_record(bench):
    r = bench["router"]
    await r.handle("status")
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("what is the airspeed of an unladen swallow?")
    root = bench["root"]
    # every turn-log line
    for line in turn_lines(root):
        assert line["profile"] in ("work", "personal")
    # every persisted registry record
    for p in (root / "registry" / "surfaces").glob("*.json"):
        assert json.loads(p.read_text())["profile"] in ("work", "personal")
    # every corpus record
    for p in (root / "corpus").rglob("*.md"):
        assert "profile:" in p.read_text()
    # every switchboard commit
    log = subprocess.run(["git", "log", "--format=%s"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    for line in log.splitlines():
        if line.startswith("switchboard:"):
            assert "profile=" in line


async def test_gc8_unclassified_op_refused_as_class_x(bench):
    import re
    from operator_router.toolrouter import CatalogueEntry

    ran = []

    async def run(m):
        ran.append(1)
        return "poked"

    bench["router"].catalogue.append(CatalogueEntry(
        op_name="poke_prod", label="poke prod",
        pattern=re.compile(r"^poke prod$"), readback=None, run=run,
        token_fetch=None))
    reply = await bench["router"].handle("poke prod")
    assert ran == [] and "confirm poke prod" in reply.lower()
