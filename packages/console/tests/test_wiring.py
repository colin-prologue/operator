import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.models import Surface
from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_switchboard_mcp.storage import CorpusStore
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


def build_surface_router(tmp_path: Path, *, llm_reply: str = "llm says hi") -> tuple[Router, StubLLM]:
    """A router wired only against the local surface registry -- no MCP
    bridge needed, since surface_register/surface_list/surface_kill never
    call it."""
    registry = SurfaceRegistry(tmp_path)
    opreg = OperationRegistry()
    seed_operation_classes(opreg)
    llm = StubLLM(reply=llm_reply)
    router = Router(registry=registry, opreg=opreg, machine=ConfirmationMachine(),
                    catalogue=[], llm=llm, turnlog=TurnLog(tmp_path / "logs" / "turns.jsonl"))
    router.catalogue.extend(build_catalogue(None, registry, router.context))
    return router, llm


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    import subprocess
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def test_seeded_classes_match_the_spec_table():
    opreg = OperationRegistry()
    seed_operation_classes(opreg)
    assert opreg.classify("ticket_list") is OpClass.R
    assert opreg.classify("ticket_transition") is OpClass.C
    assert opreg.classify("gate_stamp") is OpClass.G
    assert opreg.classify("surface_kill") is OpClass.X


async def test_full_bench_flow_over_real_mcp(corpus_root):
    """Register surfaces, move a ticket with read-back->confirm, verify
    token consumption — goal conditions 1, 3 and the grammar exchange."""
    CorpusStore(corpus_root, profile="personal").ticket_create(
        "cache-concurrency", "Investigate the cache race.")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(corpus_root), "--profile", "personal"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bridge = McpBridge(session)
            registry = SurfaceRegistry(corpus_root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            llm = StubLLM()
            router = Router(
                registry=registry, opreg=opreg,
                machine=ConfirmationMachine(),
                catalogue=build_catalogue(bridge, registry, None),
                llm=llm, turnlog=TurnLog(corpus_root / "logs" / "turns.jsonl"),
            )

            # goal condition 1: register two kinds, resolve by name
            r1 = await router.handle(
                "register tmux build-box at tmux:main")
            assert "confirm register" in r1
            await router.handle("confirm register")
            await router.handle(
                "register chat proxy-pilot at claude://claude.ai/chat/abc")
            await router.handle("confirm register")
            assert registry.resolve("build-box").surface is not None
            assert registry.resolve("proxy-pilot").surface.kind == "chat"

            # tier-2 read is Class R: no confirmation
            listing = await router.handle("list tickets")
            assert "cache-concurrency" in listing

            # the canonical grammar exchange
            rb = await router.handle("move cache-concurrency to needs-review")
            assert "confirm move" in rb
            done = await router.handle("confirm move")
            assert "needs-review" in done
            assert (await bridge.call("ticket_read",
                                      {"name": "cache-concurrency"}))["lane"] \
                == "needs-review"
            assert llm.calls == []


async def test_confirm_after_out_of_band_move_aborts_stale(corpus_root):
    """Grammar spec: record moved under the read-back -> stale token aborts
    with a fresh read-back offer; the op is NOT re-applied."""
    CorpusStore(corpus_root, profile="personal").ticket_create(
        "cache-concurrency", "Investigate the cache race.")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(corpus_root), "--profile", "personal"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bridge = McpBridge(session)
            registry = SurfaceRegistry(corpus_root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            llm = StubLLM()
            router = Router(registry=registry, opreg=opreg,
                            machine=ConfirmationMachine(), catalogue=[],
                            llm=llm,
                            turnlog=TurnLog(corpus_root / "logs" / "turns.jsonl"))
            router.catalogue.extend(build_catalogue(bridge, registry, router.context))

            rb = await router.handle("move cache-concurrency to needs-review")
            assert "confirm move" in rb
            # out-of-band mutation bumps the revision under the read-back
            await bridge.call("ticket_transition", {
                "name": "cache-concurrency", "to_lane": "in-progress",
                "token": "rev0"})
            reply = await router.handle("confirm move")
            assert "fresh read-back" in reply.lower()
            t = await bridge.call("ticket_read", {"name": "cache-concurrency"})
            assert t["lane"] == "in-progress"   # NOT re-applied
            assert t["revision"] == 1


async def test_kill_arms_with_resolved_label_and_executes(tmp_path):
    router, llm = build_surface_router(tmp_path)
    router.registry.register(Surface(
        name="build-box", kind="tmux", address="tmux:main", digest="d",
        profile="personal", registered_at="2026-07-08T00:00:00+00:00"))

    rb = await router.handle("kill build-box")
    assert 'confirm kill build-box' in rb.lower()
    assert router.registry.resolve("build-box").surface is not None  # not yet killed

    reply = await router.handle("confirm kill build-box")
    assert "killed" in reply.lower() and "build-box" in reply
    assert router.registry.resolve("build-box").surface is None
    assert llm.calls == []


async def test_kill_unknown_surface_does_not_arm(tmp_path):
    router, llm = build_surface_router(tmp_path)

    reply = await router.handle("kill ghost")
    assert "no surface" in reply.lower()
    assert "confirm kill" not in reply.lower()
    assert router.machine.state == "IDLE"

    # the machine never armed, so a later "confirm kill ghost" is inert
    # w.r.t. the confirmation machine and falls through to the LLM stub.
    reply2 = await router.handle("confirm kill ghost")
    assert reply2 == "llm says hi"
    assert llm.calls == ["confirm kill ghost"]


async def test_kill_fuzzy_match_does_not_arm_with_mismatched_label(tmp_path):
    """Grammar principle 2: the armed label always names the exact
    resolved target -- a typo that fuzzy-resolves to a different surface
    must not arm under the typed (wrong) name."""
    router, llm = build_surface_router(tmp_path)
    router.registry.register(Surface(
        name="build-box", kind="tmux", address="tmux:main", digest="d",
        profile="personal", registered_at="2026-07-08T00:00:00+00:00"))

    reply = await router.handle("kill buld-box")   # typo, close match
    assert "did you mean build-box" in reply.lower()
    assert "confirm kill" not in reply.lower()
    assert router.machine.state == "IDLE"
    assert router.registry.resolve("build-box").surface is not None
