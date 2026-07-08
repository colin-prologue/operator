import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_switchboard_mcp.storage import CorpusStore

EXPECTED_TOOLS = {
    "ticket_list", "ticket_read", "ticket_transition", "ticket_comment",
    "gate_read", "gate_stamp", "corpus_query",
}


async def test_stdio_roundtrip_lists_tools_and_moves_a_ticket(corpus_root):
    # seed outside the server, as the bench spec does
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
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == EXPECTED_TOOLS
            # spec classes surface in descriptions
            by_name = {t.name: t.description for t in tools.tools}
            assert by_name["ticket_list"].rstrip().endswith("[class:R]")
            assert by_name["gate_stamp"].rstrip().endswith("[class:G]")

            listed = await session.call_tool("ticket_list", {})
            payload = json.loads(listed.content[0].text)
            assert payload[0]["name"] == "cache-concurrency"

            moved = await session.call_tool(
                "ticket_transition",
                {"name": "cache-concurrency", "to_lane": "needs-review",
                 "token": "rev0"})
            assert json.loads(moved.content[0].text)["status"] == "applied"

            replay = await session.call_tool(
                "ticket_transition",
                {"name": "cache-concurrency", "to_lane": "needs-review",
                 "token": "rev0"})
            assert json.loads(replay.content[0].text)["status"] == "already_applied"


async def test_unknown_names_return_structured_errors(corpus_root):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(corpus_root), "--profile", "personal"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("ticket_read", {"name": "ghost"})
            payload = json.loads(result.content[0].text)
            assert payload["status"] == "error"
            assert "ghost" in payload["message"]
            result = await session.call_tool(
                "ticket_transition",
                {"name": "ghost", "to_lane": "done", "token": "rev0"})
            assert json.loads(result.content[0].text)["status"] == "error"
