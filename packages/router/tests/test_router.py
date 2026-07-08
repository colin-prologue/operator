import re
from pathlib import Path

import pytest

from operator_registry.models import Surface
from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.toolrouter import CatalogueEntry
from operator_router.turnlog import TurnLog


def surface(name, kind="chat"):
    return Surface(name=name, kind=kind, address="claude://x", digest="d",
                   profile="personal", registered_at="2026-07-08T00:00:00+00:00")


def build(tmp_path: Path, catalogue=None, opreg=None):
    reg = SurfaceRegistry(tmp_path)
    reg.register(surface("proxy-pilot"))
    reg.register(surface("build-box", "tmux"))
    opreg = opreg or OperationRegistry()
    llm = StubLLM(reply="llm says hi")
    log = TurnLog(tmp_path / "logs" / "turns.jsonl")
    router = Router(registry=reg, opreg=opreg, machine=ConfirmationMachine(),
                    catalogue=catalogue or [], llm=llm, turnlog=log)
    return router, llm, log


async def test_switch_surface_is_tier1_with_zero_llm_calls(tmp_path):
    router, llm, log = build(tmp_path)
    reply = await router.handle("switch to build box")
    assert "build-box" in reply
    assert router.context.surface == "build-box"
    assert llm.calls == []                      # goal condition 2
    assert log.lines()[-1]["tier"] == 1


async def test_ambiguous_switch_offers_candidates(tmp_path):
    router, llm, log = build(tmp_path)
    router.registry.register(surface("build-bot"))
    reply = await router.handle("switch to build")
    assert "build-box" in reply and "build-bot" in reply
    assert router.context.surface is None


async def test_unmatched_text_falls_through_to_tier3(tmp_path):
    router, llm, log = build(tmp_path)
    reply = await router.handle("what changed in the repo overnight?")
    assert reply == "llm says hi"
    assert llm.calls == ["what changed in the repo overnight?"]
    assert log.lines()[-1]["tier"] == 3        # goal condition 5


async def test_profile_switch_is_sticky_and_logged(tmp_path):
    router, llm, log = build(tmp_path)
    await router.handle("work mode")
    assert router.context.profile == "work"
    assert log.lines()[-1]["profile"] == "work"


async def test_class_r_tool_runs_without_confirmation(tmp_path):
    ran = []

    async def run(m, token):
        ran.append(1)
        return "two tickets in backlog"

    opreg = OperationRegistry()
    opreg.assign("ticket_list", OpClass.R)
    entry = CatalogueEntry(op_name="ticket_list", label="list",
                           pattern=re.compile(r"^list tickets$"),
                           readback=None, run=run, token_fetch=None)
    router, llm, log = build(tmp_path, catalogue=[entry], opreg=opreg)
    reply = await router.handle("list tickets")
    assert reply == "two tickets in backlog" and ran == [1]
    assert log.lines()[-1]["tier"] == 2


async def test_class_c_tool_demands_keyword_confirmation(tmp_path):
    ran = []
    tokens = []

    async def run(m, token):
        ran.append(1)
        tokens.append(token)
        return "moved"

    async def readback(m):
        return 'Moving cache-concurrency to needs-review. Say "confirm move".'

    opreg = OperationRegistry()
    opreg.assign("ticket_transition", OpClass.C)
    entry = CatalogueEntry(op_name="ticket_transition", label="move",
                           pattern=re.compile(r"^move (?P<name>[\w-]+) to (?P<lane>[\w-]+)$"),
                           readback=readback, run=run, token_fetch=None)
    router, llm, log = build(tmp_path, catalogue=[entry], opreg=opreg)

    reply = await router.handle("move cache-concurrency to needs-review")
    assert 'confirm move' in reply and ran == []
    assert (await router.handle("yes")) != "moved" and ran == []   # inert
    reply = await router.handle("confirm move")
    assert reply == "moved" and ran == [1]
    assert tokens == [None]   # entry has no token_fetch -> armed token is None


async def test_unclassified_op_is_refused_as_class_x(tmp_path):
    """Goal condition 8: unclassified op -> Class X behavior (confirmation
    demanded), even with no explicit read-back builder."""
    ran = []

    async def run(m, token):
        ran.append(1)
        return "launched"

    entry = CatalogueEntry(op_name="launch_missiles", label="launch missiles",
                           pattern=re.compile(r"^launch missiles$"),
                           readback=None, run=run, token_fetch=None)
    router, llm, log = build(tmp_path, catalogue=[entry])  # never assigned
    reply = await router.handle("launch missiles")
    assert ran == []
    assert "confirm launch missiles" in reply.lower()
    reply = await router.handle("confirm launch missiles")
    assert reply == "launched" and ran == [1]


async def test_cancel_while_awaiting_aborts_arm(tmp_path):
    async def run(m, token):
        return "moved"

    async def readback(m):
        return 'Say "confirm move".'

    opreg = OperationRegistry()
    opreg.assign("ticket_transition", OpClass.C)
    entry = CatalogueEntry(op_name="ticket_transition", label="move",
                           pattern=re.compile(r"^move it$"), readback=readback,
                           run=run, token_fetch=None)
    router, llm, log = build(tmp_path, catalogue=[entry], opreg=opreg)
    await router.handle("move it")
    reply = await router.handle("cancel")
    assert "dropped" in reply.lower()
    assert (await router.handle("confirm move")) != "moved"


async def test_dispatch_exception_still_logs_the_turn(tmp_path):
    async def boom(m, token):
        raise RuntimeError("kaboom")

    opreg = OperationRegistry()
    opreg.assign("exploding_op", OpClass.R)
    entry = CatalogueEntry(op_name="exploding_op", label="explode",
                           pattern=re.compile(r"^explode$"),
                           readback=None, run=boom, token_fetch=None)
    router, llm, log = build(tmp_path, catalogue=[entry], opreg=opreg)
    with pytest.raises(RuntimeError):
        await router.handle("explode")
    line = log.lines()[-1]
    assert line["outcome"] == "error:RuntimeError"
    assert line["profile"] == "personal"
