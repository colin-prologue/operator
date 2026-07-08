from __future__ import annotations

import time
from dataclasses import dataclass

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.confirmation import ArmedOp, ConfirmationMachine
from operator_router.fastpath import match_fastpath
from operator_router.llm import LLMFallback
from operator_router.toolrouter import CatalogueEntry, match_tool
from operator_router.turnlog import TurnLog

# CatalogueEntry.readback may return a string prefixed with this sentinel to
# refuse arming (see toolrouter.CatalogueEntry docstring).
NO_ARM_SENTINEL = "[no-arm] "


@dataclass
class RouterContext:
    profile: str = "personal"
    surface: str | None = None
    mode: str = "command"


class Router:
    """Priority chain: fast-path -> tool router -> LLM fallback.

    Every turn resolves a surface context, logs tier + latency + profile,
    and passes through the confirmation machine's AWAITING lifecycle."""

    def __init__(self, *, registry: SurfaceRegistry, opreg: OperationRegistry,
                 machine: ConfirmationMachine, catalogue: list[CatalogueEntry],
                 llm: LLMFallback, turnlog: TurnLog, profile: str = "personal",
                 clock=time.monotonic) -> None:
        self.registry = registry
        self.opreg = opreg
        self.machine = machine
        self.catalogue = catalogue
        self.llm = llm
        self.turnlog = turnlog
        self.context = RouterContext(profile=profile)
        self._clock = clock

    async def handle(self, text: str) -> str:
        start = self._clock()
        tier, outcome = 0, "error"
        try:
            tier, reply = await self._dispatch(text)
            outcome = "ok"
            return reply
        except Exception as e:
            outcome = f"error:{type(e).__name__}"
            raise
        finally:
            self.turnlog.append(
                profile=self.context.profile, surface=self.context.surface,
                tier=tier, latency_ms=(self._clock() - start) * 1000.0,
                input_preview=text, outcome=outcome,
            )

    async def _dispatch(self, text: str) -> tuple[int, str]:
        now = self._clock()
        awaiting = self.machine.state == "AWAITING"

        # confirmation traffic (incl. aborts) is owned by the machine first
        if awaiting:
            outcome = self.machine.handle(text, now)
            if outcome.kind == "confirmed":
                return 1, await outcome.armed.execute()
            if outcome.kind in ("aborted", "expired", "reprompt"):
                return 1, outcome.message
            # "pass": fall through to normal routing

        # tier 1: fast-path (zero LLM)
        hit = match_fastpath(text, awaiting=False)
        if hit:
            return 1, self._fastpath(hit)

        # tier 2: tool router over the registered catalogue
        matched = match_tool(text, self.catalogue)
        if matched:
            entry, m = matched
            return 2, await self._execute_classified(entry, m, now)

        # tier 3: LLM fallback
        return 3, await self.llm.complete(text)

    def _fastpath(self, hit) -> str:
        intent, args = hit.intent, hit.args
        if intent == "switch_surface":
            res = self.registry.resolve(args["name"])
            if res.surface:
                self.context.surface = res.surface.name
                return f"Switched to {res.surface.name} ({res.surface.kind})."
            if res.candidates:
                return "Which one: " + ", ".join(res.candidates) + "?"
            return f"No surface named {args['name']!r} is registered."
        if intent == "profile_work":
            self.context.profile = "work"
            return "Work profile active. Sticky until you switch back." + self._profile_switch_caveat()
        if intent == "profile_personal":
            self.context.profile = "personal"
            return "Personal profile active." + self._profile_switch_caveat()
        if intent == "mode_command":
            self.context.mode = "command"
            return "Command mode."
        if intent == "mode_dictation":
            self.context.mode = "dictation"
            return "Dictation mode."
        if intent == "status":
            return (f"Surface: {self.context.surface or 'none'} · "
                    f"profile: {self.context.profile} · mode: {self.context.mode}.")
        return f"Acknowledged: {intent}."

    def _profile_switch_caveat(self) -> str:
        # documented restriction (LOG-001 wart 15): the switchboard MCP
        # server is spawned once with a fixed --profile, so a mid-session
        # profile switch here doesn't change which profile corpus writes
        # land under until the console restarts.
        if not self.catalogue:
            return ""
        return " Note: the switchboard session keeps its launch profile until restart."

    async def _execute_classified(self, entry: CatalogueEntry, m, now: float) -> str:
        cls = self.opreg.classify(entry.op_name)
        if cls is OpClass.R:
            return await entry.run(m, None)
        # C / G / X (and unassigned -> X): read-back then AWAITING
        label = entry.label_for(m) if entry.label_for else entry.label
        token = await entry.token_fetch(m) if entry.token_fetch else None
        if entry.readback is not None:
            readback = await entry.readback(m)
        else:
            readback = (f"{entry.op_name} is Class {cls.value}"
                        f"{' (unclassified — defaulting to X)' if not self.opreg.is_assigned(entry.op_name) else ''}."
                        f' Say "confirm {label}".')

        # a readback can refuse to arm at all (e.g. target failed to
        # resolve) via the "[no-arm] " sentinel — see CatalogueEntry.readback
        if readback.startswith(NO_ARM_SENTINEL):
            return readback[len(NO_ARM_SENTINEL):]

        async def execute() -> str:
            return await entry.run(m, token)

        return self.machine.arm(
            ArmedOp(label=label, op_name=entry.op_name, op_class=cls,
                    readback=readback, token=token, execute=execute),
            now,
        )
