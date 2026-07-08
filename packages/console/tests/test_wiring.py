import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_switchboard_mcp.storage import CorpusStore
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


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
