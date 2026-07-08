from __future__ import annotations

import asyncio
from typing import Protocol


class LLMFallback(Protocol):
    async def complete(self, prompt: str) -> str: ...


class StubLLM:
    """Test stub; records every prompt so tests can prove zero LLM calls."""

    def __init__(self, reply: str = "stub reply") -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.reply


class ClaudeCLI:
    """LLM fallback via the local `claude` CLI (subscription tokens,
    no API-key plumbing). Tier 3 of the priority chain."""

    def __init__(self, command: tuple[str, ...] = ("claude", "-p")) -> None:
        self._command = command

    async def complete(self, prompt: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command, prompt, "--output-format", "text",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return (f"LLM fallback unavailable: `{self._command[0]}` CLI "
                    f"not found on PATH.")
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return (f"LLM fallback failed (exit {proc.returncode}): "
                    f"{stderr.decode().strip()[:200]}")
        return stdout.decode().strip()
