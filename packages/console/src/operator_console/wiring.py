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
    surfaces); it may be `None` (defaults to the "personal" profile)."""

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
    async def run_register(m, token):
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

    async def run_list_surfaces(m, token):
        surfaces = registry.list()
        if not surfaces:
            return "No surfaces registered."
        return " · ".join(f"{s.name} ({s.kind})" for s in surfaces)

    add("surface_list", "list surfaces", r"^list surfaces$", run_list_surfaces)

    def normalize_surface_name(name: str) -> str:
        # mirrors SurfaceRegistry.resolve's own spoken-style normalization
        return name.strip().lower().replace(" ", "-")

    def resolve_kill_target(name: str) -> Surface | None:
        # Class X may only bind to the exact name it arms under (grammar
        # principle 2): the resolved surface's name must match the arm-time
        # normalized name, case-insensitively (registered names may carry
        # uppercase). Fuzzy neighbors -- and a target that vanished and let
        # resolve() fall through to an unrelated close match -- never count.
        res = registry.resolve(name)
        normalized = normalize_surface_name(name)
        if res.surface is not None and res.surface.name.lower() == normalized:
            return res.surface
        return None

    async def run_kill(m, token):
        # re-resolve at confirm time -- the exact target may have vanished
        # (or a same-shaped neighbor may now fuzzy-win) out-of-band between
        # arm and confirm. Only the exact name armed under may be killed;
        # anything else executes against nothing rather than a neighbor.
        normalized = normalize_surface_name(m["name"])
        target = resolve_kill_target(m["name"])
        if target is None:
            return f"Surface {normalized!r} is no longer registered — nothing killed."
        registry.kill(target.name)
        return f"Killed surface {target.name}."

    async def rb_kill(m):
        target = resolve_kill_target(m["name"])
        if target is not None:
            return (f"Killing surface {target.name} — this removes its "
                    f"registration entirely. Say \"confirm kill {target.name}\".")
        res = registry.resolve(m["name"])
        if res.surface is not None:
            # fuzzy/case-mismatched: refuse to arm so the armed label always
            # names the exact resolved target (grammar principle 2), and
            # make the user re-issue verbatim.
            return (f"[no-arm] Did you mean {res.surface.name}? "
                    f"Say \"kill {res.surface.name}\".")
        if res.candidates:
            return "[no-arm] Which one: " + ", ".join(res.candidates) + "?"
        return f"[no-arm] No surface named {m['name']!r} is registered."

    def kill_label(m):
        # Class X label carries the target name (grammar: names the
        # operation). Mirrors resolve_kill_target so the armed label always
        # agrees with the readback's instruction -- including resolved
        # casing (e.g. "kill MyBot", not "kill mybot") -- and falls back to
        # the normalized typed name only when rb_kill is about to refuse to
        # arm anyway (that label is discarded, never surfaced).
        target = resolve_kill_target(m["name"])
        return f"kill {target.name if target else normalize_surface_name(m['name'])}"

    entries.append(CatalogueEntry(
        op_name="surface_kill", label="kill",
        pattern=re.compile(r"^kill (?P<name>[\w-]+)$"),
        readback=rb_kill, run=run_kill, token_fetch=None,
        label_for=kill_label))

    # --- tickets (over MCP) --------------------------------------------
    async def run_ticket_list(m, token):
        lane = m.groupdict().get("lane")
        tickets = await bridge.call("ticket_list",
                                    {"lane": lane} if lane else {})
        if not tickets:
            return "No tickets."
        return " · ".join(f"{t['name']} [{t['lane']} rev{t['revision']}]"
                          for t in tickets)

    add("ticket_list", "list tickets",
        r"^list tickets(?: in (?P<lane>[\w-]+))?$", run_ticket_list)

    async def run_ticket_read(m, token):
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

    async def run_move(m, token):
        # submit the token captured at read-back time — NOT a fresh read —
        # so a record that moved under the read-back aborts stale instead
        # of being silently re-applied against the current revision.
        result = await bridge.call("ticket_transition", {
            "name": m["name"], "to_lane": m["lane"], "token": token})
        status = result.get("status")
        if status == "applied":
            return f"Done — {m['name']} is in {m['lane']}."
        if status == "already_applied":
            return f"Already applied — {m['name']} was moved earlier."
        if status == "stale_token":
            return (f"The ticket moved to revision "
                    f"{result['current_revision']} since the read-back — "
                    f"want a fresh read-back?")
        return f"That didn't apply: {result.get('message', result)}"

    add("ticket_transition", "move",
        r"^move (?P<name>[\w-]+) to (?P<lane>[\w-]+)$",
        run_move, rb_move, fetch_ticket_token)

    async def rb_comment(m):
        return (f"Attaching your comment to {m['name']}: "
                f"“{m['body'][:80]}”. Say \"confirm comment\".")

    async def run_comment(m, token):
        result = await bridge.call("ticket_comment",
                                   {"name": m["name"], "body": m["body"]})
        if result.get("status") == "applied":
            return f"Comment attached to {m['name']}."
        return f"That didn't apply: {result.get('message', result)}"

    add("ticket_comment", "comment",
        r"^comment on (?P<name>[\w-]+): (?P<body>.+)$",
        run_comment, rb_comment)

    # --- gates -----------------------------------------------------------
    async def run_gate_read(m, token):
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

    async def run_stamp(m, token):
        state = m.groupdict().get("state") or "approved"
        # submit the token captured at read-back time — NOT a fresh read —
        # so a gate that moved under the read-back aborts stale instead of
        # being silently re-applied against the current revision.
        result = await bridge.call("gate_stamp", {
            "name": m["name"], "state": state, "token": token})
        status = result.get("status")
        if status == "applied":
            return (f"Stamped. {m['name']} {state} at revision "
                    f"{result['revision']}.")
        if status == "already_applied":
            return "Already applied at the current revision."
        if status == "stale_token":
            return (f"Hold on — the gate moved to revision "
                    f"{result['current_revision']}. Want the updated "
                    f"read-back?")
        return f"That didn't apply: {result.get('message', result)}"

    # gate label is dynamic: "gate <name>" (grammar: confirm gate <name>)
    entries.append(CatalogueEntry(
        op_name="gate_stamp", label="gate", pattern=re.compile(
            r"^stamp gate (?P<name>[\w-]+)(?: as (?P<state>[\w-]+))?$"),
        readback=rb_stamp, run=run_stamp, token_fetch=fetch_gate_token,
        label_for=lambda m: f"gate {m['name']}"))

    # --- corpus search ---------------------------------------------------
    async def run_query(m, token):
        hits = await bridge.call("corpus_query", {"text": m["text"]})
        if not hits:
            return "Nothing in the corpus matches."
        return "\n".join(f"{h['path']}: {h['snippet']}" for h in hits[:5])

    add("corpus_query", "search", r"^search for (?P<text>.+)$", run_query)

    return entries
