from __future__ import annotations

import datetime as dt
import json
import re

from mcp import ClientSession

from operator_registry.models import Surface
from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.toolrouter import CatalogueEntry

SPEC_CLASSES: dict[str, OpClass] = {
    "ticket_list": OpClass.R,
    "ticket_read": OpClass.R,
    "gate_read": OpClass.R,
    "corpus_query": OpClass.R,
    "surface_list": OpClass.R,
    "ticket_transition": OpClass.C,
    "ticket_comment": OpClass.C,
    "surface_register": OpClass.C,
    "gate_stamp": OpClass.G,
    "surface_kill": OpClass.X,
}


def seed_operation_classes(opreg: OperationRegistry) -> None:
    for op, cls in SPEC_CLASSES.items():
        opreg.assign(op, cls)


class McpBridge:
    """Thin client-side wrapper: call a switchboard tool, parse JSON text."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def call(self, tool: str, args: dict) -> dict | list:
        result = await self._session.call_tool(tool, args)
        return json.loads(result.content[0].text)


def build_catalogue(bridge: McpBridge, registry: SurfaceRegistry,
                    context) -> list[CatalogueEntry]:
    """The bench vocabulary: deterministic patterns -> classified ops.

    `context` is the RouterContext (for the profile flag on registered
    surfaces); it may be attached after Router construction via
    `attach_context`."""

    holder = {"context": context}

    def profile() -> str:
        ctx = holder["context"]
        return ctx.profile if ctx else "personal"

    entries: list[CatalogueEntry] = []

    def add(op_name, label, pattern, run, readback=None, token_fetch=None):
        entries.append(CatalogueEntry(
            op_name=op_name, label=label, pattern=re.compile(pattern),
            readback=readback, run=run, token_fetch=token_fetch))

    # --- surfaces (local registry ops) --------------------------------
    async def run_register(m):
        registry.register(Surface(
            name=m["name"], kind=m["kind"], address=m["address"],
            digest="registered via console", profile=profile(),
            registered_at=dt.datetime.now(dt.UTC).isoformat()))
        return f"Registered {m['kind']} surface {m['name']}."

    async def rb_register(m):
        return (f"Registering {m['kind']} surface {m['name']} at "
                f"{m['address']}. Say \"confirm register\".")

    add("surface_register", "register",
        r"^register (?P<kind>chat|cowork|code|tmux) (?P<name>[\w-]+) at (?P<address>\S+)$",
        run_register, rb_register)

    async def run_list_surfaces(m):
        surfaces = registry.list()
        if not surfaces:
            return "No surfaces registered."
        return " · ".join(f"{s.name} ({s.kind})" for s in surfaces)

    add("surface_list", "list surfaces", r"^list surfaces$", run_list_surfaces)

    async def run_kill(m):
        registry.kill(m["name"])
        return f"Killed surface {m['name']}."

    async def rb_kill(m):
        res = registry.resolve(m["name"])
        found = res.surface.name if res.surface else m["name"]
        return (f"Killing surface {found} — this removes its registration "
                f"entirely. Say \"confirm kill {found}\".")

    # Class X label carries the target name (grammar: names the operation)
    entries.append(CatalogueEntry(
        op_name="surface_kill", label="kill",
        pattern=re.compile(r"^kill (?P<name>[\w-]+)$"),
        readback=rb_kill, run=run_kill, token_fetch=None,
        label_for=lambda m: f"kill {m['name']}"))

    # --- tickets (over MCP) --------------------------------------------
    async def run_ticket_list(m):
        lane = m.groupdict().get("lane")
        tickets = await bridge.call("ticket_list",
                                    {"lane": lane} if lane else {})
        if not tickets:
            return "No tickets."
        return " · ".join(f"{t['name']} [{t['lane']} rev{t['revision']}]"
                          for t in tickets)

    add("ticket_list", "list tickets",
        r"^list tickets(?: in (?P<lane>[\w-]+))?$", run_ticket_list)

    async def run_ticket_read(m):
        t = await bridge.call("ticket_read", {"name": m["name"]})
        return (f"{t['name']} [{t['lane']} rev{t['revision']}]\n{t['body']}")

    add("ticket_read", "read ticket", r"^read ticket (?P<name>[\w-]+)$",
        run_ticket_read)

    async def fetch_ticket_token(m):
        t = await bridge.call("ticket_read", {"name": m["name"]})
        return f"rev{t['revision']}"

    async def rb_move(m):
        t = await bridge.call("ticket_read", {"name": m["name"]})
        return (f"Moving {m['name']} from {t['lane']} to {m['lane']} "
                f"(rev{t['revision']}). Say \"confirm move\".")

    async def run_move(m):
        t = await bridge.call("ticket_read", {"name": m["name"]})
        result = await bridge.call("ticket_transition", {
            "name": m["name"], "to_lane": m["lane"],
            "token": f"rev{t['revision']}"})
        if result.get("status") == "applied":
            return f"Done — {m['name']} is in {m['lane']}."
        if result.get("status") == "already_applied":
            return f"Already applied — {m['name']} was moved earlier."
        return (f"The ticket moved to revision "
                f"{result.get('current_revision')} since the read-back — "
                f"want a fresh read-back?")

    add("ticket_transition", "move",
        r"^move (?P<name>[\w-]+) to (?P<lane>[\w-]+)$",
        run_move, rb_move, fetch_ticket_token)

    async def rb_comment(m):
        return (f"Attaching your comment to {m['name']}: "
                f"“{m['body'][:80]}”. Say \"confirm comment\".")

    async def run_comment(m):
        await bridge.call("ticket_comment",
                          {"name": m["name"], "body": m["body"]})
        return f"Comment attached to {m['name']}."

    add("ticket_comment", "comment",
        r"^comment on (?P<name>[\w-]+): (?P<body>.+)$",
        run_comment, rb_comment)

    # --- gates -----------------------------------------------------------
    async def run_gate_read(m):
        g = await bridge.call("gate_read", {"name": m["name"]})
        return f"Gate {g['name']} is {g['state']} at revision {g['revision']}."

    add("gate_read", "read gate", r"^read gate (?P<name>[\w-]+)$",
        run_gate_read)

    async def rb_stamp(m):
        g = await bridge.call("gate_read", {"name": m["name"]})
        state = m.groupdict().get("state") or "approved"
        return (f"Gate “{g['name']}” is at {g['state']}, revision "
                f"{g['revision']}. Stamping {state}. "
                f"Say \"confirm gate {g['name']}\".")

    async def fetch_gate_token(m):
        g = await bridge.call("gate_read", {"name": m["name"]})
        return f"rev{g['revision']}"

    async def run_stamp(m):
        g = await bridge.call("gate_read", {"name": m["name"]})
        state = m.groupdict().get("state") or "approved"
        result = await bridge.call("gate_stamp", {
            "name": m["name"], "state": state,
            "token": f"rev{g['revision']}"})
        if result.get("status") == "applied":
            return (f"Stamped. {m['name']} {state} at revision "
                    f"{result['revision']}.")
        if result.get("status") == "already_applied":
            return "Already applied at the current revision."
        return (f"Hold on — the gate moved to revision "
                f"{result.get('current_revision')}. Want the updated "
                f"read-back?")

    # gate label is dynamic: "gate <name>" (grammar: confirm gate <name>)
    entries.append(CatalogueEntry(
        op_name="gate_stamp", label="gate", pattern=re.compile(
            r"^stamp gate (?P<name>[\w-]+)(?: as (?P<state>[\w-]+))?$"),
        readback=rb_stamp, run=run_stamp, token_fetch=fetch_gate_token,
        label_for=lambda m: f"gate {m['name']}"))

    # --- corpus search ---------------------------------------------------
    async def run_query(m):
        hits = await bridge.call("corpus_query", {"text": m["text"]})
        if not hits:
            return "Nothing in the corpus matches."
        return "\n".join(f"{h['path']}: {h['snippet']}" for h in hits[:5])

    add("corpus_query", "search", r"^search for (?P<text>.+)$", run_query)

    return entries


def attach_context(entries_holder_context, context) -> None:
    """Late-bind the RouterContext into the catalogue's profile closure."""
    entries_holder_context["context"] = context
