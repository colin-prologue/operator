from __future__ import annotations

import enum


class OpClass(enum.Enum):
    R = "R"  # reversible — no confirmation, narrated
    C = "C"  # confirmable — read-back + keyword confirm
    G = "G"  # gate-crossing — C + decision-log write, token consumed
    X = "X"  # destructive — C + non-interruptible + scoped read-back


class OperationRegistry:
    """Operation classes are registry data (constitution art. 1).

    Unassigned operations default to Class X (constitution art. 1)."""

    def __init__(self) -> None:
        self._classes: dict[str, OpClass] = {}

    def assign(self, op: str, cls: OpClass) -> None:
        self._classes[op] = cls

    def classify(self, op: str) -> OpClass:
        return self._classes.get(op, OpClass.X)

    def is_assigned(self, op: str) -> bool:
        return op in self._classes
