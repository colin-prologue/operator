import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_switchboard_mcp.storage import CorpusStore
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    store = CorpusStore(tmp_path, profile="personal")
    store.ticket_create("cache-concurrency", "Investigate the cache race.")
    store.gate_create("voice-loop", state="needs-review")
    return tmp_path


@pytest_asyncio.fixture
async def bench(corpus_root):
    """Fully wired bench rig over a real stdio MCP session.

    `stdio_client`/`ClientSession` open an anyio task group, which requires
    __aenter__/__aexit__ to run in the same asyncio Task. pytest-asyncio
    drives an async-generator fixture's setup and teardown as two separate
    Task.run() calls on the same loop, so a plain `async with ...: yield ...`
    here hits `RuntimeError: Attempted to exit cancel scope in a different
    task than it was entered in` on teardown. Instead, run the whole
    stdio_client/ClientSession lifecycle inside one long-lived background
    task (entered and exited by that same task) and hand the fixture's two
    Task.run() calls only plain Event/Task awaits; the yielded bench dict is
    unchanged."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(corpus_root), "--profile", "personal"],
    )
    ready = asyncio.Event()
    stop = asyncio.Event()
    box: dict = {}

    async def lifecycle() -> None:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                bridge = McpBridge(session)
                registry = SurfaceRegistry(corpus_root)
                opreg = OperationRegistry()
                seed_operation_classes(opreg)
                llm = StubLLM("(tier 3 reached)")
                router = Router(registry=registry, opreg=opreg,
                                machine=ConfirmationMachine(), catalogue=[],
                                llm=llm,
                                turnlog=TurnLog(corpus_root / "logs" / "turns.jsonl"))
                router.catalogue.extend(
                    build_catalogue(bridge, registry, router.context))
                box.update({"router": router, "llm": llm, "root": corpus_root,
                            "registry": registry, "bridge": bridge})
                ready.set()
                await stop.wait()

    task = asyncio.create_task(lifecycle())
    await ready.wait()
    yield box
    stop.set()
    await task
