from __future__ import annotations

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import ClaudeCLI, StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


async def run_console(root: Path, profile: str, no_llm: bool = False,
                      stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(root), "--profile", profile],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bridge = McpBridge(session)
            registry = SurfaceRegistry(root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            router = Router(
                registry=registry, opreg=opreg,
                machine=ConfirmationMachine(),
                catalogue=[], llm=StubLLM("(LLM disabled)") if no_llm else ClaudeCLI(),
                turnlog=TurnLog(root / "logs" / "turns.jsonl"),
                profile=profile,
            )
            router.catalogue.extend(
                build_catalogue(bridge, registry, router.context))
            stdout.write(f"operator console · profile={profile} · "
                         f"root={root}\n")
            stdout.flush()
            for line in stdin:
                text = line.strip()
                if not text:
                    continue
                if text in ("exit", "quit"):
                    break
                try:
                    reply = await router.handle(text)
                except Exception as e:
                    # router.handle already turn-logged the error; keep the
                    # REPL alive rather than letting one bad tool call kill
                    # the console session.
                    stdout.write(f"error: {e}\n")
                    stdout.flush()
                    continue
                stdout.write(reply + "\n")
                stdout.flush()
