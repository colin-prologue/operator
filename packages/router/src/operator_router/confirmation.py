from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from operator_router.classes import OpClass

ABORTS = ("cancel", "stop", "never mind")
TTL_SECONDS = 15.0


@dataclass
class ArmedOp:
    label: str
    op_name: str
    op_class: OpClass
    readback: str
    token: str | None
    execute: Callable[[], Awaitable[str]]


@dataclass
class Outcome:
    kind: str  # confirmed | aborted | expired | reprompt | pass
    message: str = ""
    armed: ArmedOp | None = None


class ConfirmationMachine:
    """Owns the AWAITING lifecycle (kickoff spec: lives in the router package)."""

    def __init__(self, ttl_seconds: float = TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._armed: ArmedOp | None = None
        self._armed_at = 0.0

    @property
    def state(self) -> str:
        return "AWAITING" if self._armed is not None else "IDLE"

    def arm(self, op: ArmedOp, now: float) -> str:
        # one armed op at a time; a new confirmable request drops the pending one
        self._armed = op
        self._armed_at = now
        return op.readback

    def handle(self, text: str, now: float) -> Outcome:
        if self._armed is None:
            return Outcome("pass")
        if now - self._armed_at > self._ttl:
            label = self._armed.label
            self._armed = None
            return Outcome("expired", f'Letting that go — "{label}" timed out.')
        stripped = text.strip().lower()
        if stripped in ABORTS:
            label = self._armed.label
            self._armed = None
            return Outcome("aborted", f"Dropped the pending {label}.")
        if stripped == "confirm":
            return Outcome(
                "reprompt",
                f'Say "confirm {self._armed.label}" to proceed, or "cancel".',
            )
        if stripped.startswith("confirm "):
            spoken = stripped[len("confirm "):].strip()
            if spoken == self._armed.label.lower():
                armed = self._armed
                self._armed = None
                return Outcome("confirmed", armed=armed)
            return Outcome(
                "reprompt",
                f'That does not match the armed operation. Say "confirm '
                f'{self._armed.label}" or "cancel".',
            )
        return Outcome("pass")
