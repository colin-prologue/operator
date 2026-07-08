from __future__ import annotations

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
