from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from operator_switchboard_mcp.storage import CorpusStore, StaleTokenError


def build_server(root: Path, profile: str) -> FastMCP:
    store = CorpusStore(root, profile=profile)
    mcp = FastMCP("switchboard")

    @mcp.tool(description="List tickets, optionally by lane. [class:R]")
    def ticket_list(lane: str | None = None) -> str:
        return json.dumps(store.ticket_list(lane))

    @mcp.tool(description="Read a full ticket by plain-language name. [class:R]")
    def ticket_read(name: str) -> str:
        return json.dumps(store.ticket_read(name))

    @mcp.tool(description="Move a ticket between lanes; token = current "
                          "revision; at-most-once. [class:C]")
    def ticket_transition(name: str, to_lane: str, token: str) -> str:
        try:
            return json.dumps(store.ticket_transition(name, to_lane, token))
        except StaleTokenError as e:
            return json.dumps({"status": "stale_token",
                               "current_revision": e.current_revision})

    @mcp.tool(description="Append a feedback block to a ticket. [class:C]")
    def ticket_comment(name: str, body: str) -> str:
        store.ticket_comment(name, body)
        return json.dumps({"status": "applied"})

    @mcp.tool(description="Gate state + current revision. [class:R]")
    def gate_read(name: str) -> str:
        return json.dumps(store.gate_read(name))

    @mcp.tool(description="Stamp a gate: verify token against current "
                          "revision, write decision-log entry, consume "
                          "token. [class:G]")
    def gate_stamp(name: str, state: str, token: str) -> str:
        try:
            return json.dumps(store.gate_stamp(name, state, token))
        except StaleTokenError as e:
            return json.dumps({"status": "stale_token",
                               "current_revision": e.current_revision})

    @mcp.tool(description="Search decisions/ and corpus/. [class:R]")
    def corpus_query(text: str) -> str:
        return json.dumps(store.corpus_query(text))

    return mcp
