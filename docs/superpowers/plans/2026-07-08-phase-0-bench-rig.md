# Phase 0 Bench Rig Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the voiceless Phase 0 spine — intent router, surface registry, Switchboard MCP tool v0, deep-link desktop adapter, and text console — passing the kickoff spec's eight goal conditions.

**Architecture:** Five uv-workspace packages wired by a thin console. The router runs a strict priority chain (fast-path table → tool router → LLM fallback); the confirmation state machine lives in the router package and owns the AWAITING lifecycle; the Switchboard MCP server owns token verify/consume only. All corpus mutations are git commits carrying operation + token + profile. Operation classes are registry data enforced in the router's execution layer, never in prompts.

**Tech Stack:** Python 3.12, asyncio, `mcp ~=1.28.1` (FastMCP server + ClientSession over stdio), pytest + pytest-asyncio, subprocess git, PyObjC (Quartz) in the desktop adapter only, `claude -p` subprocess as the LLM fallback.

## Global Constraints

- Python `>=3.12`; workspace root is virtual (`[tool.uv.workspace] members = ["packages/*"]`).
- `mcp ~=1.28.1` — pinned per ADR-001 action item 2; do not upgrade to v2.
- Constitution article 1: operation classes are registry data enforced in the execution layer; unclassified ops default to Class X.
- Constitution article 2: revision tokens are idempotency keys; execution at-most-once per token.
- Constitution article 4: the profile flag (`work` | `personal`) appears on **every** log line and **every** persisted record.
- Constitution article 5: `packages/desktop-adapter/src/operator_desktop_adapter/adapter.py` is the ONLY file that may import OS-automation APIs.
- Confirmation grammar v2: keyword-bound (`confirm <op label>`), bare affirmatives inert, TTL 15s, one armed op at a time, universal aborts (`cancel`/`stop`/`never mind`).
- Every switchboard mutating call → git commit message `switchboard: <op> <target> token=<token|-> profile=<profile>`.
- Import names are `operator_*` (never bare `operator` — stdlib clash).
- Tests never touch the real repo's corpus: storage tests run in `tmp_path` git repos.
- Commit after every green task; branch is `feat/v0.1.0-phase-0-bench-rig`.

---

### Task 1: Test harness + surface registry

**Files:**
- Modify: `pyproject.toml` (root — add dev dependency group + pytest config)
- Create: `packages/registry/src/operator_registry/models.py`
- Create: `packages/registry/src/operator_registry/store.py`
- Test: `packages/registry/tests/test_store.py`

**Interfaces:**
- Produces: `Surface(name, kind, address, digest, profile, registered_at)` frozen dataclass; `Resolution(surface: Surface | None, candidates: list[str])`; `SurfaceRegistry(root: Path)` with `.register(s) -> Surface`, `.list() -> list[Surface]`, `.resolve(name) -> Resolution`, `.rename(old, new) -> Surface`, `.kill(name) -> None`. Registry persists one JSON file per surface at `<root>/registry/surfaces/<name>.json`.

- [ ] **Step 1: Add dev tooling to the root**

Append to root `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.25",
    "ruff>=0.8",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages", "tests"]
```

Run: `uv sync --dev && uv run pytest --collect-only -q`
Expected: exits 0, "no tests ran" (nothing collected yet).

- [ ] **Step 2: Write the failing tests**

`packages/registry/tests/test_store.py`:

```python
import json
from pathlib import Path

import pytest

from operator_registry.models import Surface
from operator_registry.store import SurfaceRegistry


def make(name="proxy-pilot", kind="chat", profile="personal"):
    return Surface(
        name=name, kind=kind,
        address="claude://claude.ai/chat/abc" if kind == "chat" else "tmux:main",
        digest="one-line summary", profile=profile,
        registered_at="2026-07-08T00:00:00+00:00",
    )


def test_register_persists_one_json_file_per_surface(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make())
    f = tmp_path / "registry" / "surfaces" / "proxy-pilot.json"
    assert f.exists()
    data = json.loads(f.read_text())
    assert data["profile"] == "personal"  # constitution art. 4
    assert data["kind"] == "chat"


def test_register_two_kinds_and_resolve_exact(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("proxy-pilot", "chat"))
    reg.register(make("build-box", "tmux"))
    r = reg.resolve("build-box")
    assert r.surface is not None and r.surface.kind == "tmux"
    assert r.candidates == []


def test_resolve_fuzzy_single_match(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("proxy-pilot", "chat"))
    r = reg.resolve("proxy pilot")
    assert r.surface is not None and r.surface.name == "proxy-pilot"


def test_resolve_ambiguous_returns_candidates_not_a_guess(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("proxy-pilot", "chat"))
    reg.register(make("proxy-pilot-2", "tmux"))
    r = reg.resolve("proxy")
    assert r.surface is None
    assert sorted(r.candidates) == ["proxy-pilot", "proxy-pilot-2"]


def test_resolve_no_match(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    r = reg.resolve("ghost")
    assert r.surface is None and r.candidates == []


def test_rename_and_kill(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("proxy-pilot", "chat"))
    reg.rename("proxy-pilot", "pilot")
    assert reg.resolve("pilot").surface is not None
    assert not (tmp_path / "registry" / "surfaces" / "proxy-pilot.json").exists()
    reg.kill("pilot")
    assert reg.list() == []


def test_invalid_kind_or_profile_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        Surface(name="x", kind="carrier-pigeon", address="a", digest="d",
                profile="personal", registered_at="2026-07-08T00:00:00+00:00")
    with pytest.raises(ValueError):
        Surface(name="x", kind="chat", address="a", digest="d",
                profile="corporate", registered_at="2026-07-08T00:00:00+00:00")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/registry -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'operator_registry.models'`

- [ ] **Step 4: Implement models + store**

`packages/registry/src/operator_registry/models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass

KINDS = ("chat", "cowork", "code", "tmux")
PROFILES = ("work", "personal")


@dataclass(frozen=True)
class Surface:
    name: str
    kind: str
    address: str
    digest: str
    profile: str
    registered_at: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown surface kind: {self.kind!r}")
        if self.profile not in PROFILES:
            raise ValueError(f"unknown profile: {self.profile!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Surface":
        return cls(**data)
```

`packages/registry/src/operator_registry/store.py`:

```python
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path

from operator_registry.models import Surface


@dataclass
class Resolution:
    surface: Surface | None
    candidates: list[str] = field(default_factory=list)


class SurfaceRegistry:
    def __init__(self, root: Path) -> None:
        self._dir = Path(root) / "registry" / "surfaces"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    def register(self, surface: Surface) -> Surface:
        self._path(surface.name).write_text(
            json.dumps(surface.to_dict(), indent=2) + "\n"
        )
        return surface

    def list(self) -> list[Surface]:
        return sorted(
            (Surface.from_dict(json.loads(p.read_text()))
             for p in self._dir.glob("*.json")),
            key=lambda s: s.name,
        )

    def resolve(self, name: str) -> Resolution:
        if self._path(name).exists():
            return Resolution(Surface.from_dict(json.loads(self._path(name).read_text())))
        names = [s.name for s in self.list()]
        # spoken-style tolerance: normalize spaces/hyphens, then fuzzy + prefix
        norm = name.strip().lower().replace(" ", "-")
        if norm in names:
            return Resolution(self._load(norm))
        close = difflib.get_close_matches(norm, names, n=5, cutoff=0.75)
        prefixed = [n for n in names if n.startswith(norm)]
        candidates = sorted(set(close) | set(prefixed))
        if len(candidates) == 1:
            return Resolution(self._load(candidates[0]))
        return Resolution(None, candidates)

    def _load(self, name: str) -> Surface:
        return Surface.from_dict(json.loads(self._path(name).read_text()))

    def rename(self, old: str, new: str) -> Surface:
        res = self.resolve(old)
        if res.surface is None:
            raise KeyError(old)
        renamed = Surface(**{**res.surface.to_dict(), "name": new})
        self.register(renamed)
        self._path(res.surface.name).unlink()
        return renamed

    def kill(self, name: str) -> None:
        res = self.resolve(name)
        if res.surface is None:
            raise KeyError(name)
        self._path(res.surface.name).unlink()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/registry -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock packages/registry
git commit -m "feat(registry): surface registry with exact+fuzzy resolution"
```

---

### Task 2: Operation class registry + confirmation state machine

**Files:**
- Create: `packages/router/src/operator_router/classes.py`
- Create: `packages/router/src/operator_router/confirmation.py`
- Test: `packages/router/tests/test_classes.py`
- Test: `packages/router/tests/test_confirmation.py`

**Interfaces:**
- Produces: `OpClass` enum (`R`, `C`, `G`, `X`); `OperationRegistry` with `.assign(op: str, cls: OpClass)`, `.classify(op: str) -> OpClass` (default `X`), `.is_assigned(op: str) -> bool`.
- Produces: `ConfirmationMachine(ttl_seconds=15.0)` with `.state` (`"IDLE"` | `"AWAITING"`), `.arm(op: ArmedOp, now: float) -> str` (returns read-back, drops any pending arm), `.handle(text: str, now: float) -> Outcome`. `ArmedOp(label, op_name, op_class, readback, token, execute)` where `execute: Callable[[], Awaitable[str]]`. `Outcome(kind, message, armed)` with `kind` in `{"confirmed", "aborted", "expired", "reprompt", "pass"}` — `"confirmed"` carries `armed` for the executor; `"pass"` means input was not confirmation traffic.

- [ ] **Step 1: Write the failing tests**

`packages/router/tests/test_classes.py`:

```python
from operator_router.classes import OperationRegistry, OpClass


def test_default_class_is_x_for_unassigned_ops():
    reg = OperationRegistry()
    assert reg.classify("brand_new_capability") is OpClass.X
    assert not reg.is_assigned("brand_new_capability")


def test_assigned_class_is_returned():
    reg = OperationRegistry()
    reg.assign("ticket_list", OpClass.R)
    reg.assign("gate_stamp", OpClass.G)
    assert reg.classify("ticket_list") is OpClass.R
    assert reg.classify("gate_stamp") is OpClass.G
    assert reg.is_assigned("ticket_list")
```

`packages/router/tests/test_confirmation.py`:

```python
import pytest

from operator_router.classes import OpClass
from operator_router.confirmation import ArmedOp, ConfirmationMachine


async def noop() -> str:
    return "done"


def arm_op(label="move", op="ticket_transition", cls=OpClass.C, token=None):
    return ArmedOp(label=label, op_name=op, op_class=cls,
                   readback=f"Read-back for {label}. Say \"confirm {label}\".",
                   token=token, execute=noop)


def test_arm_enters_awaiting_and_returns_readback():
    m = ConfirmationMachine()
    rb = m.arm(arm_op(), now=0.0)
    assert m.state == "AWAITING"
    assert 'confirm move' in rb


def test_exact_keyword_confirms():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm move", now=1.0)
    assert out.kind == "confirmed" and out.armed.label == "move"
    assert m.state == "IDLE"


def test_bare_affirmatives_are_inert():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    for text in ("yes", "yeah", "sure", "do it"):
        assert m.handle(text, now=1.0).kind == "pass"
    assert m.state == "AWAITING"


def test_bare_confirm_reprompts_without_executing():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm", now=1.0)
    assert out.kind == "reprompt"
    assert m.state == "AWAITING"


def test_wrong_operation_word_reprompts():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    out = m.handle("confirm remove", now=1.0)
    assert out.kind == "reprompt"
    assert m.state == "AWAITING"


def test_universal_aborts():
    for word in ("cancel", "stop", "never mind"):
        m = ConfirmationMachine()
        m.arm(arm_op(), now=0.0)
        out = m.handle(word, now=1.0)
        assert out.kind == "aborted"
        assert m.state == "IDLE"


def test_ttl_expiry_lets_it_go():
    m = ConfirmationMachine()
    m.arm(arm_op(), now=0.0)
    out = m.handle("confirm move", now=15.1)
    assert out.kind == "expired"
    assert "letting that go" in out.message.lower()
    assert m.state == "IDLE"


def test_new_arm_drops_pending_op():
    m = ConfirmationMachine()
    m.arm(arm_op("move"), now=0.0)
    m.arm(arm_op("send"), now=1.0)
    assert m.handle("confirm move", now=2.0).kind == "reprompt"
    assert m.handle("confirm send", now=3.0).kind == "confirmed"


def test_idle_machine_passes_everything():
    m = ConfirmationMachine()
    assert m.handle("confirm move", now=0.0).kind == "pass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/router -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'operator_router.classes'`

- [ ] **Step 3: Implement**

`packages/router/src/operator_router/classes.py`:

```python
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
```

`packages/router/src/operator_router/confirmation.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/router -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add packages/router
git commit -m "feat(router): operation class registry + confirmation state machine"
```

---

### Task 3: Turn log + fast-path table

**Files:**
- Create: `packages/router/src/operator_router/turnlog.py`
- Create: `packages/router/src/operator_router/fastpath.py`
- Test: `packages/router/tests/test_turnlog.py`
- Test: `packages/router/tests/test_fastpath.py`

**Interfaces:**
- Produces: `TurnLog(path: Path)` with `.append(*, profile, surface, tier, latency_ms, input_preview, outcome) -> None` — one JSON line per turn, `profile` mandatory (raises `ValueError` if falsy); `.lines() -> list[dict]` for tests.
- Produces: `FastPathHit(intent: str, args: dict)`; `match_fastpath(text: str, awaiting: bool) -> FastPathHit | None`. Intents: `stop`, `cancel`, `pause`, `resume`, `status`, `switch_surface` (args `{"name": ...}`), `mode_command`, `mode_dictation`, `profile_work`, `profile_personal`, `confirmation` (only when `awaiting=True`).

- [ ] **Step 1: Write the failing tests**

`packages/router/tests/test_turnlog.py`:

```python
import json
from pathlib import Path

import pytest

from operator_router.turnlog import TurnLog


def test_append_writes_json_line_with_profile(tmp_path: Path):
    log = TurnLog(tmp_path / "logs" / "turns.jsonl")
    log.append(profile="personal", surface="proxy-pilot", tier=1,
               latency_ms=0.4, input_preview="status", outcome="ok")
    lines = log.lines()
    assert len(lines) == 1
    assert lines[0]["profile"] == "personal"
    assert lines[0]["tier"] == 1
    raw = (tmp_path / "logs" / "turns.jsonl").read_text().splitlines()
    assert json.loads(raw[0])["surface"] == "proxy-pilot"


def test_profile_is_mandatory_on_every_line(tmp_path: Path):
    log = TurnLog(tmp_path / "turns.jsonl")
    with pytest.raises(ValueError):
        log.append(profile="", surface=None, tier=3, latency_ms=1.0,
                   input_preview="x", outcome="ok")
```

`packages/router/tests/test_fastpath.py`:

```python
from operator_router.fastpath import match_fastpath


def test_core_commands_hit():
    for text, intent in [("stop", "stop"), ("cancel", "cancel"),
                         ("pause", "pause"), ("resume", "resume"),
                         ("status", "status")]:
        hit = match_fastpath(text, awaiting=False)
        assert hit is not None and hit.intent == intent


def test_switch_to_surface_extracts_name():
    hit = match_fastpath("switch to proxy pilot", awaiting=False)
    assert hit is not None
    assert hit.intent == "switch_surface"
    assert hit.args["name"] == "proxy pilot"


def test_mode_and_profile_switches():
    assert match_fastpath("command mode", awaiting=False).intent == "mode_command"
    assert match_fastpath("dictation mode", awaiting=False).intent == "mode_dictation"
    assert match_fastpath("work mode", awaiting=False).intent == "profile_work"
    assert match_fastpath("personal mode", awaiting=False).intent == "profile_personal"


def test_confirmation_keywords_live_only_inside_awaiting():
    assert match_fastpath("confirm move", awaiting=False) is None
    hit = match_fastpath("confirm move", awaiting=True)
    assert hit is not None and hit.intent == "confirmation"


def test_unknown_text_misses():
    assert match_fastpath("summarize the repo deltas", awaiting=False) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/router/tests/test_turnlog.py packages/router/tests/test_fastpath.py -v`
Expected: FAIL — modules not found

- [ ] **Step 3: Implement**

`packages/router/src/operator_router/turnlog.py`:

```python
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


class TurnLog:
    """Append-only JSONL turn log. Every line carries the profile flag
    (constitution art. 4)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *, profile: str, surface: str | None, tier: int,
               latency_ms: float, input_preview: str, outcome: str) -> None:
        if not profile:
            raise ValueError("profile flag is mandatory on every log line")
        record = {
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "profile": profile,
            "surface": surface,
            "tier": tier,
            "latency_ms": round(latency_ms, 3),
            "input_preview": input_preview[:120],
            "outcome": outcome,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def lines(self) -> list[dict]:
        if not self._path.exists():
            return []
        return [json.loads(line) for line in self._path.read_text().splitlines()]
```

`packages/router/src/operator_router/fastpath.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Fast-path table v1 (kickoff spec): exact + small synonym set; no LLM.
_EXACT: dict[str, str] = {
    "stop": "stop",
    "cancel": "cancel",
    "never mind": "cancel",
    "pause": "pause",
    "resume": "resume",
    "status": "status",
    "command mode": "mode_command",
    "dictation mode": "mode_dictation",
    "work mode": "profile_work",
    "personal mode": "profile_personal",
}

_SWITCH = re.compile(r"^(?:switch to|go to)\s+(?P<name>.+)$")


@dataclass
class FastPathHit:
    intent: str
    args: dict = field(default_factory=dict)


def match_fastpath(text: str, awaiting: bool) -> FastPathHit | None:
    stripped = text.strip().lower()
    if stripped in _EXACT:
        return FastPathHit(_EXACT[stripped])
    m = _SWITCH.match(stripped)
    if m:
        return FastPathHit("switch_surface", {"name": m.group("name").strip()})
    # confirmation keywords are live only inside AWAITING (grammar principle 4)
    if awaiting and stripped.startswith("confirm"):
        return FastPathHit("confirmation", {"text": text.strip()})
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/router -v`
Expected: all router tests pass (Task 2's 12 + these 8 = 20)

- [ ] **Step 5: Commit**

```bash
git add packages/router
git commit -m "feat(router): turn log + fast-path table v1"
```

---

### Task 4: Router priority chain + execution-layer class enforcement

**Files:**
- Create: `packages/router/src/operator_router/llm.py`
- Create: `packages/router/src/operator_router/toolrouter.py`
- Create: `packages/router/src/operator_router/router.py`
- Test: `packages/router/tests/test_router.py`

**Interfaces:**
- Consumes: Task 1 `SurfaceRegistry`/`Resolution`; Task 2 `OperationRegistry`, `OpClass`, `ConfirmationMachine`, `ArmedOp`, `Outcome`; Task 3 `TurnLog`, `match_fastpath`.
- Produces: `LLMFallback` protocol with `async def complete(self, prompt: str) -> str`; `StubLLM(reply="...")` recording `.calls: list[str]`.
- Produces: `CatalogueEntry(op_name: str, pattern: re.Pattern, readback: Callable[[re.Match], Awaitable[str]] | None, run: Callable[[re.Match], Awaitable[str]], label: str, token_fetch: Callable[[re.Match], Awaitable[str | None]] | None)` — `readback` builds the Class C/G/X read-back sentence; `run` executes.
- Produces: `Router(registry, opreg, machine, catalogue, llm, turnlog, profile="personal", clock=time.monotonic)` with `async def handle(self, text: str) -> str` and `.context` (`RouterContext(profile, surface, mode)`). Tier numbering in the turn log: 1 = fast-path, 2 = tool router, 3 = LLM fallback.

- [ ] **Step 1: Write the failing tests**

`packages/router/tests/test_router.py`:

```python
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

    async def run(m):
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

    async def run(m):
        ran.append(1)
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


async def test_unclassified_op_is_refused_as_class_x(tmp_path):
    """Goal condition 8: unclassified op -> Class X behavior (confirmation
    demanded), even with no explicit read-back builder."""
    ran = []

    async def run(m):
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
    async def run(m):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/router/tests/test_router.py -v`
Expected: FAIL — modules not found

- [ ] **Step 3: Implement**

`packages/router/src/operator_router/llm.py`:

```python
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
```

`packages/router/src/operator_router/toolrouter.py`:

```python
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class CatalogueEntry:
    """One tool-router tier entry: deterministic pattern -> operation."""

    op_name: str
    label: str  # confirmation keyword label, e.g. "move"
    pattern: re.Pattern
    readback: Callable[[re.Match], Awaitable[str]] | None
    run: Callable[[re.Match], Awaitable[str]]
    token_fetch: Callable[[re.Match], Awaitable[str | None]] | None
    # dynamic label per match, e.g. "gate voice-loop" / "kill build-box"
    # (grammar principle 2: the confirmation names the operation)
    label_for: Callable[[re.Match], str] | None = None


def match_tool(text: str, catalogue: list[CatalogueEntry]) -> tuple[CatalogueEntry, re.Match] | None:
    stripped = text.strip()
    for entry in catalogue:
        m = entry.pattern.match(stripped)
        if m:
            return entry, m
    return None
```

`packages/router/src/operator_router/router.py`:

```python
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
        tier, reply = await self._dispatch(text)
        self.turnlog.append(
            profile=self.context.profile, surface=self.context.surface,
            tier=tier, latency_ms=(self._clock() - start) * 1000.0,
            input_preview=text, outcome="ok",
        )
        return reply

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
            return "Work profile active. Sticky until you switch back."
        if intent == "profile_personal":
            self.context.profile = "personal"
            return "Personal profile active."
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

    async def _execute_classified(self, entry: CatalogueEntry, m, now: float) -> str:
        cls = self.opreg.classify(entry.op_name)
        if cls is OpClass.R:
            return await entry.run(m)
        # C / G / X (and unassigned -> X): read-back then AWAITING
        label = entry.label_for(m) if entry.label_for else entry.label
        token = await entry.token_fetch(m) if entry.token_fetch else None
        if entry.readback is not None:
            readback = await entry.readback(m)
        else:
            readback = (f"{entry.op_name} is Class {cls.value}"
                        f"{' (unclassified — defaulting to X)' if not self.opreg.is_assigned(entry.op_name) else ''}."
                        f' Say "confirm {label}".')

        async def execute() -> str:
            return await entry.run(m)

        return self.machine.arm(
            ArmedOp(label=label, op_name=entry.op_name, op_class=cls,
                    readback=readback, token=token, execute=execute),
            now,
        )
```

Note: `packages/router/pyproject.toml` gains a workspace dependency:

```toml
dependencies = ["operator-registry"]

[tool.uv.sources]
operator-registry = { workspace = true }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv sync && uv run pytest packages/router -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/router pyproject.toml uv.lock
git commit -m "feat(router): priority chain with execution-layer class enforcement"
```

---

### Task 5: Switchboard corpus store + revision tokens

**Files:**
- Create: `packages/switchboard-mcp/src/operator_switchboard_mcp/storage.py`
- Test: `packages/switchboard-mcp/tests/test_storage.py`
- Test fixture helper: `packages/switchboard-mcp/tests/conftest.py`

**Interfaces:**
- Produces: `CorpusStore(root: Path, profile: str)`. Tickets are markdown files with frontmatter (`name`, `revision`, `last_applied_token`, `profile`) in `corpus/tickets/<lane>/<name>.md`; gates are `corpus/gates/<name>.md` with (`state`, `revision`, `last_applied_token`, `profile`).
- Methods: `.ticket_list(lane: str | None) -> list[dict]` (each `{"name", "lane", "revision"}`); `.ticket_read(name) -> dict` (`{"name","lane","revision","body"}`); `.ticket_transition(name, to_lane, token) -> dict` (`{"status": "applied"|"already_applied", "revision": int}`, raises `StaleTokenError(current_revision)` on stale); `.ticket_comment(name, body) -> None`; `.gate_read(name) -> dict` (`{"name","state","revision"}`); `.gate_stamp(name, state, token) -> dict` (same idempotency contract; writes `decisions/GATE-<name>-rev<N>.md`); `.corpus_query(text) -> list[dict]` (`{"path", "snippet"}`).
- Token format: `"rev<N>"` where N is the record's current revision. Apply → revision becomes N+1, `last_applied_token` = the consumed token. Replay of `last_applied_token` → `{"status": "already_applied"}`, no commit. Any other token → `StaleTokenError` carrying `current_revision`.
- Every mutating method commits with message `switchboard: <op> <target> token=<token|-> profile=<profile>` (constitution arts. 2, 4).

- [ ] **Step 1: Write the fixture + failing tests**

`packages/switchboard-mcp/tests/conftest.py`:

```python
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    """A throwaway git repo with the corpus layout. Never the real repo."""
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path
```

`packages/switchboard-mcp/tests/test_storage.py`:

```python
import subprocess
from pathlib import Path

import pytest

from operator_switchboard_mcp.storage import CorpusStore, StaleTokenError


def git_log(root: Path) -> list[str]:
    out = subprocess.run(["git", "log", "--format=%s"], cwd=root,
                         check=True, capture_output=True, text=True)
    return out.stdout.splitlines()


def seed_ticket(store: CorpusStore, name="cache-concurrency"):
    store.ticket_create(name, "Investigate the cache race.", lane="backlog")
    return name


def test_ticket_create_list_read(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    tickets = store.ticket_list()
    assert [t["name"] for t in tickets] == ["cache-concurrency"]
    assert store.ticket_list(lane="done") == []
    t = store.ticket_read("cache-concurrency")
    assert t["lane"] == "backlog" and t["revision"] == 0
    assert "cache race" in t["body"]


def test_transition_moves_file_and_commits_with_token_and_profile(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    result = store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    assert result == {"status": "applied", "revision": 1}
    assert store.ticket_read("cache-concurrency")["lane"] == "needs-review"
    head = git_log(corpus_root)[0]
    assert "ticket_transition" in head and "token=rev0" in head
    assert "profile=personal" in head           # goal conditions 3 + 7


def test_transition_replay_is_verified_noop(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    commits_before = len(git_log(corpus_root))
    replay = store.ticket_transition("cache-concurrency", "needs-review", "rev0")
    assert replay["status"] == "already_applied"
    assert len(git_log(corpus_root)) == commits_before  # no second commit


def test_transition_stale_token_reports_current_revision(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    store.ticket_transition("cache-concurrency", "in-progress", "rev0")
    with pytest.raises(StaleTokenError) as exc:
        store.ticket_transition("cache-concurrency", "done", "rev99")
    assert exc.value.current_revision == 1


def test_comment_appends_feedback_block_and_commits(corpus_root):
    store = CorpusStore(corpus_root, profile="work")
    seed_ticket(store)
    store.ticket_comment("cache-concurrency", "Looks racy around evict().")
    body = store.ticket_read("cache-concurrency")["body"]
    assert "Looks racy around evict()" in body
    head = git_log(corpus_root)[0]
    assert "ticket_comment" in head and "profile=work" in head and "token=-" in head


def test_gate_stamp_exactly_once_and_decision_log(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    store.gate_create("voice-loop", state="needs-review")
    g = store.gate_read("voice-loop")
    assert g["revision"] == 0

    result = store.gate_stamp("voice-loop", "approved", "rev0")
    assert result == {"status": "applied", "revision": 1}   # goal condition 4
    assert store.gate_read("voice-loop")["state"] == "approved"
    record = corpus_root / "decisions" / "GATE-voice-loop-rev1.md"
    assert record.exists()
    assert "profile: personal" in record.read_text()

    replay = store.gate_stamp("voice-loop", "approved", "rev0")
    assert replay["status"] == "already_applied"

    with pytest.raises(StaleTokenError) as exc:
        store.gate_stamp("voice-loop", "approved", "rev0-bogus")
    assert exc.value.current_revision == 1


def test_corpus_query_searches_decisions_and_corpus(corpus_root):
    store = CorpusStore(corpus_root, profile="personal")
    seed_ticket(store)
    hits = store.corpus_query("cache race")
    assert any("cache-concurrency" in h["path"] for h in hits)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/switchboard-mcp -v`
Expected: FAIL — `No module named 'operator_switchboard_mcp.storage'`

- [ ] **Step 3: Implement**

`packages/switchboard-mcp/src/operator_switchboard_mcp/storage.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

LANES = ("backlog", "in-progress", "needs-review", "done")


class StaleTokenError(Exception):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"stale token; current revision is {current_revision}")


def _parse(text: str) -> tuple[dict, str]:
    """Split '---' frontmatter from body. Values are plain strings/ints."""
    lines = text.splitlines()
    assert lines and lines[0] == "---", "record missing frontmatter"
    meta: dict = {}
    i = 1
    while lines[i] != "---":
        key, _, value = lines[i].partition(":")
        meta[key.strip()] = value.strip()
        i += 1
    meta["revision"] = int(meta.get("revision", "0"))
    return meta, "\n".join(lines[i + 1:]).lstrip("\n")


def _render(meta: dict, body: str) -> str:
    front = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{front}\n---\n\n{body.rstrip()}\n"


class CorpusStore:
    """Git-backed file storage with directory-lane transitions.

    Owns token verify/consume only; classification lives in the router
    (kickoff spec: 'the MCP tool only verifies and consumes tokens')."""

    def __init__(self, root: Path, profile: str) -> None:
        if profile not in ("work", "personal"):
            raise ValueError(f"unknown profile: {profile!r}")
        self.root = Path(root)
        self.profile = profile

    # -- git plumbing -----------------------------------------------------
    def _commit(self, op: str, target: str, token: str | None,
                paths: list[Path]) -> None:
        rel = [str(p.relative_to(self.root)) for p in paths]
        subprocess.run(["git", "add", "-A", "--", *rel], cwd=self.root, check=True)
        msg = f"switchboard: {op} {target} token={token or '-'} profile={self.profile}"
        subprocess.run(["git", "commit", "-q", "-m", msg, "--", *rel],
                       cwd=self.root, check=True)

    # -- tickets ----------------------------------------------------------
    def _lane_dir(self, lane: str) -> Path:
        if lane not in LANES:
            raise ValueError(f"unknown lane: {lane!r}")
        return self.root / "corpus" / "tickets" / lane

    def _find_ticket(self, name: str) -> tuple[Path, str]:
        for lane in LANES:
            p = self._lane_dir(lane) / f"{name}.md"
            if p.exists():
                return p, lane
        raise KeyError(f"no ticket named {name!r}")

    def ticket_create(self, name: str, body: str, lane: str = "backlog") -> None:
        p = self._lane_dir(lane) / f"{name}.md"
        meta = {"name": name, "revision": 0, "last_applied_token": "-",
                "profile": self.profile}
        p.write_text(_render(meta, body))
        self._commit("ticket_create", name, None, [p])

    def ticket_list(self, lane: str | None = None) -> list[dict]:
        lanes = [lane] if lane else list(LANES)
        out = []
        for ln in lanes:
            for p in sorted(self._lane_dir(ln).glob("*.md")):
                meta, _ = _parse(p.read_text())
                out.append({"name": meta["name"], "lane": ln,
                            "revision": meta["revision"]})
        return out

    def ticket_read(self, name: str) -> dict:
        p, lane = self._find_ticket(name)
        meta, body = _parse(p.read_text())
        return {"name": name, "lane": lane, "revision": meta["revision"],
                "body": body}

    def _apply_token(self, meta: dict, token: str) -> str:
        """Returns 'applied' | 'already_applied'; raises StaleTokenError."""
        current = f"rev{meta['revision']}"
        if token == current:
            return "applied"
        if token == meta.get("last_applied_token"):
            return "already_applied"
        raise StaleTokenError(meta["revision"])

    def ticket_transition(self, name: str, to_lane: str, token: str) -> dict:
        src, lane = self._find_ticket(name)
        meta, body = _parse(src.read_text())
        status = self._apply_token(meta, token)
        if status == "already_applied":
            return {"status": status, "revision": meta["revision"]}
        meta["revision"] += 1
        meta["last_applied_token"] = token
        dst = self._lane_dir(to_lane) / src.name
        src.unlink()
        dst.write_text(_render(meta, body))
        self._commit("ticket_transition", f"{name}->{to_lane}", token, [src, dst])
        return {"status": "applied", "revision": meta["revision"]}

    def ticket_comment(self, name: str, body: str) -> None:
        p, _ = self._find_ticket(name)
        meta, existing = _parse(p.read_text())
        block = f"\n\n## Feedback ({self.profile})\n\n{body.rstrip()}\n"
        p.write_text(_render(meta, existing + block))
        self._commit("ticket_comment", name, None, [p])

    # -- gates ------------------------------------------------------------
    def _gate_path(self, name: str) -> Path:
        return self.root / "corpus" / "gates" / f"{name}.md"

    def gate_create(self, name: str, state: str = "open") -> None:
        p = self._gate_path(name)
        meta = {"name": name, "state": state, "revision": 0,
                "last_applied_token": "-", "profile": self.profile}
        p.write_text(_render(meta, f"Gate {name}."))
        self._commit("gate_create", name, None, [p])

    def gate_read(self, name: str) -> dict:
        p = self._gate_path(name)
        if not p.exists():
            raise KeyError(f"no gate named {name!r}")
        meta, _ = _parse(p.read_text())
        return {"name": name, "state": meta["state"],
                "revision": meta["revision"]}

    def gate_stamp(self, name: str, state: str, token: str) -> dict:
        p = self._gate_path(name)
        if not p.exists():
            raise KeyError(f"no gate named {name!r}")
        meta, body = _parse(p.read_text())
        status = self._apply_token(meta, token)
        if status == "already_applied":
            return {"status": status, "revision": meta["revision"]}
        meta["revision"] += 1
        meta["last_applied_token"] = token
        meta["state"] = state
        p.write_text(_render(meta, body))
        record = self.root / "decisions" / f"GATE-{name}-rev{meta['revision']}.md"
        record.write_text(
            f"---\ngate: {name}\nstate: {state}\ntoken: {token}\n"
            f"revision: {meta['revision']}\nprofile: {self.profile}\n---\n\n"
            f"Gate {name} stamped {state} (token {token} consumed, "
            f"at-most-once).\n"
        )
        self._commit("gate_stamp", f"{name}={state}", token, [p, record])
        return {"status": "applied", "revision": meta["revision"]}

    # -- search -----------------------------------------------------------
    def corpus_query(self, text: str) -> list[dict]:
        needle = text.strip().lower()
        hits: list[dict] = []
        for base in (self.root / "decisions", self.root / "corpus"):
            for p in sorted(base.rglob("*.md")):
                content = p.read_text()
                if needle in content.lower() or needle in p.name.lower():
                    idx = max(content.lower().find(needle), 0)
                    snippet = content[max(0, idx - 40): idx + 80].strip()
                    hits.append({"path": str(p.relative_to(self.root)),
                                 "snippet": snippet})
        return hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/switchboard-mcp -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add packages/switchboard-mcp
git commit -m "feat(switchboard): git-backed corpus store with at-most-once tokens"
```

---

### Task 6: Switchboard MCP server over stdio

**Files:**
- Create: `packages/switchboard-mcp/src/operator_switchboard_mcp/server.py`
- Create: `packages/switchboard-mcp/src/operator_switchboard_mcp/__main__.py`
- Test: `packages/switchboard-mcp/tests/test_server.py`

**Interfaces:**
- Consumes: Task 5 `CorpusStore`, `StaleTokenError`.
- Produces: `build_server(root: Path, profile: str) -> FastMCP` exposing exactly the seven spec tools: `ticket_list(lane)`, `ticket_read(name)`, `ticket_transition(name, to_lane, token)`, `ticket_comment(name, body)`, `gate_read(name)`, `gate_stamp(name, state, token)`, `corpus_query(text)`. Tool descriptions end with their spec class tag, e.g. `[class:R]` — display metadata only; enforcement stays in the router (constitution art. 1).
- Produces: `python -m operator_switchboard_mcp --root <path> --profile <work|personal>` running the server on stdio.

- [ ] **Step 1: Write the failing test**

`packages/switchboard-mcp/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/switchboard-mcp/tests/test_server.py -v`
Expected: FAIL — no module named `operator_switchboard_mcp.server` / `__main__`

- [ ] **Step 3: Implement**

`packages/switchboard-mcp/src/operator_switchboard_mcp/server.py`:

```python
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
```

`packages/switchboard-mcp/src/operator_switchboard_mcp/__main__.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from operator_switchboard_mcp.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="operator-switchboard-mcp")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", choices=("work", "personal"),
                        required=True)
    args = parser.parse_args()
    build_server(args.root, args.profile).run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/switchboard-mcp -v`
Expected: all pass (Task 5's 7 + this 1)

- [ ] **Step 5: Commit**

```bash
git add packages/switchboard-mcp
git commit -m "feat(switchboard): FastMCP server exposing the seven v0 tools over stdio"
```

---

### Task 7: Desktop adapter (one file) + manual smoke script

**Files:**
- Create: `packages/desktop-adapter/src/operator_desktop_adapter/adapter.py`
- Create: `packages/desktop-adapter/smoke.py` (manual script, not pytest)
- Modify: `packages/desktop-adapter/pyproject.toml` (add PyObjC Quartz dep, darwin-only)
- Test: `packages/desktop-adapter/tests/test_adapter.py`

**Interfaces:**
- Produces: `adapter.open(address: str) -> None` (fires the deep link via the OS URL handler — `/usr/bin/open` subprocess; raises `ValueError` on schemes outside `claude://`, `claude-cli://`); `adapter.send() -> None` (synthesizes Return via Quartz `CGEventPost`; Quartz imported lazily inside `send()` so importing the module never requires PyObjC).
- This is the ONLY file allowed to import OS-automation APIs (constitution art. 5).

- [ ] **Step 1: Add the dependency**

In `packages/desktop-adapter/pyproject.toml` set:

```toml
dependencies = ["pyobjc-framework-Quartz>=10; sys_platform == 'darwin'"]
```

- [ ] **Step 2: Write the failing tests**

`packages/desktop-adapter/tests/test_adapter.py`:

```python
from unittest.mock import patch

import pytest

from operator_desktop_adapter import adapter


def test_open_fires_the_os_url_handler():
    with patch("operator_desktop_adapter.adapter.subprocess.run") as run:
        adapter.open("claude://claude.ai/new?q=hello")
        run.assert_called_once_with(
            ["/usr/bin/open", "claude://claude.ai/new?q=hello"], check=True)


def test_open_rejects_non_claude_schemes():
    for bad in ("https://example.com", "file:///etc/passwd", "osascript://x"):
        with pytest.raises(ValueError):
            adapter.open(bad)


def test_module_import_does_not_require_quartz():
    # send() imports Quartz lazily; module import must succeed anywhere
    assert hasattr(adapter, "send")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest packages/desktop-adapter -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement the one file**

`packages/desktop-adapter/src/operator_desktop_adapter/adapter.py`:

```python
"""Deep-link dispatch + send seam. THE one file allowed to touch
OS-automation APIs (constitution art. 5). Keep it small, keep it
replaceable — this is the most brittle seam in the system.

Manual smoke script: packages/desktop-adapter/smoke.py — run it after
every Claude Desktop update."""

from __future__ import annotations

import subprocess

_ALLOWED_SCHEMES = ("claude://", "claude-cli://")
_RETURN_KEYCODE = 36


def open(address: str) -> None:
    """Fire a deep link via the OS URL handler. Prefills but does not send."""
    if not address.startswith(_ALLOWED_SCHEMES):
        raise ValueError(f"refusing non-claude deep link: {address!r}")
    subprocess.run(["/usr/bin/open", address], check=True)


def send() -> None:
    """Issue the final Enter via macOS Accessibility (CGEventPost).

    Requires the Accessibility TCC grant on the hosting interpreter.
    Quartz is imported lazily so importing this module never needs PyObjC."""
    from Quartz import (  # noqa: PLC0415 — lazy by design
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
    )

    for key_down in (True, False):
        event = CGEventCreateKeyboardEvent(None, _RETURN_KEYCODE, key_down)
        CGEventPost(kCGHIDEventTap, event)
```

`packages/desktop-adapter/smoke.py`:

```python
"""Manual smoke test for the desktop adapter. Run after every Claude
Desktop update:

    uv run python packages/desktop-adapter/smoke.py

Exercises: (1) open() prefills a chat via claude://, (2) after a pause for
the app to focus, send() issues the final Enter. Verify by eye that the
message actually sent. Requires the Accessibility grant for the terminal
(System Settings > Privacy & Security > Accessibility)."""

import time

from operator_desktop_adapter import adapter

if __name__ == "__main__":
    adapter.open("claude://claude.ai/new?q=smoke%20test%20from%20operator")
    print("deep link fired; waiting 5s for Claude Desktop to focus…")
    time.sleep(5)
    adapter.send()
    print("Enter sent. Check Claude Desktop: the message should be sent.")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv sync && uv run pytest packages/desktop-adapter -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add packages/desktop-adapter pyproject.toml uv.lock
git commit -m "feat(desktop-adapter): one-file deep-link + send seam with manual smoke script"
```

---

### Task 8: Console + Claude CLI fallback + bench catalogue

**Files:**
- Create: `packages/console/src/operator_console/wiring.py`
- Create: `packages/console/src/operator_console/app.py`
- Create: `packages/console/src/operator_console/__main__.py`
- Modify: `packages/console/pyproject.toml` (workspace deps on registry, router, switchboard-mcp + `mcp`)
- Modify: `packages/router/src/operator_router/llm.py` (add `ClaudeCLI`)
- Test: `packages/console/tests/test_wiring.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_catalogue(session: "McpBridge", registry: SurfaceRegistry, context) -> list[CatalogueEntry]` — the bench vocabulary (see table in Step 1). `McpBridge` wraps an MCP `ClientSession` with `async def call(tool: str, args: dict) -> dict` (parses the JSON text content). `seed_operation_classes(opreg)` assigns the spec table: `ticket_list/ticket_read/gate_read/corpus_query/surface_list -> R`; `ticket_transition/ticket_comment/surface_register -> C`; `gate_stamp -> G`; `surface_kill -> X`.
- Produces: `ClaudeCLI(command=("claude", "-p"))` implementing `LLMFallback` via subprocess (`claude -p <prompt> --output-format text`), with a clear error string if the CLI is missing.
- Produces: `python -m operator_console --root <path> --profile <p> [--no-llm]` — REPL reading stdin lines, printing router replies; `--no-llm` swaps in `StubLLM` (bench mode).

- [ ] **Step 1: Write the failing tests**

Bench catalogue vocabulary (tier 2):

| Input pattern | op_name | label | Class |
|---|---|---|---|
| `register <kind> <name> at <address>` | surface_register | register | C |
| `list surfaces` | surface_list | — | R |
| `kill <name>` | surface_kill | kill <name> | X |
| `list tickets( in <lane>)?` | ticket_list | — | R |
| `read ticket <name>` | ticket_read | — | R |
| `move <name> to <lane>` | ticket_transition | move | C |
| `comment on <name>: <body>` | ticket_comment | comment | C |
| `read gate <name>` | gate_read | — | R |
| `stamp gate <name>( as <state>)?` | gate_stamp | gate <name> | G |
| `search for <text>` | corpus_query | — | R |

`packages/console/tests/test_wiring.py`:

```python
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry, OpClass
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_switchboard_mcp.storage import CorpusStore
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    import subprocess
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def test_seeded_classes_match_the_spec_table():
    opreg = OperationRegistry()
    seed_operation_classes(opreg)
    assert opreg.classify("ticket_list") is OpClass.R
    assert opreg.classify("ticket_transition") is OpClass.C
    assert opreg.classify("gate_stamp") is OpClass.G
    assert opreg.classify("surface_kill") is OpClass.X


async def test_full_bench_flow_over_real_mcp(corpus_root):
    """Register surfaces, move a ticket with read-back->confirm, verify
    token consumption — goal conditions 1, 3 and the grammar exchange."""
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
            bridge = McpBridge(session)
            registry = SurfaceRegistry(corpus_root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            llm = StubLLM()
            router = Router(
                registry=registry, opreg=opreg,
                machine=ConfirmationMachine(),
                catalogue=build_catalogue(bridge, registry, None),
                llm=llm, turnlog=TurnLog(corpus_root / "logs" / "turns.jsonl"),
            )

            # goal condition 1: register two kinds, resolve by name
            r1 = await router.handle(
                "register tmux build-box at tmux:main")
            assert "confirm register" in r1
            await router.handle("confirm register")
            r2 = await router.handle(
                "register chat proxy-pilot at claude://claude.ai/chat/abc")
            await router.handle("confirm register")
            assert registry.resolve("build-box").surface is not None
            assert registry.resolve("proxy-pilot").surface.kind == "chat"

            # tier-2 read is Class R: no confirmation
            listing = await router.handle("list tickets")
            assert "cache-concurrency" in listing

            # the canonical grammar exchange
            rb = await router.handle("move cache-concurrency to needs-review")
            assert "confirm move" in rb
            done = await router.handle("confirm move")
            assert "needs-review" in done
            assert (await bridge.call("ticket_read",
                                      {"name": "cache-concurrency"}))["lane"] \
                == "needs-review"
            assert llm.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/console -v`
Expected: FAIL — `operator_console.wiring` not found

- [ ] **Step 3: Implement**

`packages/console/pyproject.toml` dependencies:

```toml
dependencies = [
    "operator-registry",
    "operator-router",
    "operator-switchboard-mcp",
    "mcp~=1.28.1",
]

[tool.uv.sources]
operator-registry = { workspace = true }
operator-router = { workspace = true }
operator-switchboard-mcp = { workspace = true }
```

Add to `packages/router/src/operator_router/llm.py`:

```python
import asyncio


class ClaudeCLI:
    """LLM fallback via the local `claude` CLI (subscription tokens,
    no API-key plumbing). Tier 3 of the priority chain."""

    def __init__(self, command: tuple[str, ...] = ("claude", "-p")) -> None:
        self._command = command

    async def complete(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *self._command, prompt, "--output-format", "text",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return (f"LLM fallback failed (exit {proc.returncode}): "
                    f"{stderr.decode().strip()[:200]}")
        return stdout.decode().strip()
```

`packages/console/src/operator_console/wiring.py`:

```python
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
            digest=f"registered via console", profile=profile(),
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
```

> Implementation note for the executor: `build_catalogue` reads the profile
> through the `holder` closure; the standard wiring is to build the `Router`
> first with an empty catalogue, then
> `router.catalogue.extend(build_catalogue(bridge, registry, router.context))`.
> The Task 8 test constructs with `context=None`; `profile()` falls back to
> `"personal"` in that case. Dynamic confirmation labels
> (`confirm gate <name>`, `confirm kill <name>`) come from
> `CatalogueEntry.label_for`, already defined in Task 4.

`packages/console/src/operator_console/app.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import ClaudeCLI, StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


async def run_console(root: Path, profile: str, no_llm: bool = False,
                      stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(root), "--profile", profile],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bridge = McpBridge(session)
            registry = SurfaceRegistry(root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            router = Router(
                registry=registry, opreg=opreg,
                machine=ConfirmationMachine(),
                catalogue=[], llm=StubLLM("(LLM disabled)") if no_llm else ClaudeCLI(),
                turnlog=TurnLog(root / "logs" / "turns.jsonl"),
                profile=profile,
            )
            router.catalogue.extend(
                build_catalogue(bridge, registry, router.context))
            stdout.write(f"operator console · profile={profile} · "
                         f"root={root}\n")
            stdout.flush()
            for line in stdin:
                text = line.strip()
                if not text:
                    continue
                if text in ("exit", "quit"):
                    break
                reply = await router.handle(text)
                stdout.write(reply + "\n")
                stdout.flush()
```

`packages/console/src/operator_console/__main__.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from operator_console.app import run_console


def main() -> None:
    parser = argparse.ArgumentParser(prog="operator-console")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=("work", "personal"),
                        default="personal")
    parser.add_argument("--no-llm", action="store_true",
                        help="use the stub LLM (bench mode)")
    args = parser.parse_args()
    asyncio.run(run_console(args.root, args.profile, args.no_llm))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv sync && uv run pytest packages/console -v`
Expected: 2 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: everything green

- [ ] **Step 6: Commit**

```bash
git add packages/console packages/router pyproject.toml uv.lock
git commit -m "feat(console): REPL wiring, bench catalogue, claude CLI fallback"
```

---

### Task 9: Acceptance suite — the eight goal conditions

**Files:**
- Create: `tests/acceptance/test_goal_conditions.py`
- Create: `tests/acceptance/conftest.py` (reuse of the corpus_root + full wiring fixture)
- Modify: `.gitignore` (add `logs/` and `registry/`)

**Interfaces:**
- Consumes: everything. This task adds no production code — it proves the spec's §Acceptance criteria as named tests, one per goal condition. Goal condition 6 (desktop smoke on real Claude Desktop) is manual by design; the acceptance file documents it with a skip marker pointing at `packages/desktop-adapter/smoke.py`.

- [ ] **Step 1: Write the fixture**

`tests/acceptance/conftest.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from operator_registry.store import SurfaceRegistry
from operator_router.classes import OperationRegistry
from operator_router.confirmation import ConfirmationMachine
from operator_router.llm import StubLLM
from operator_router.router import Router
from operator_router.turnlog import TurnLog
from operator_switchboard_mcp.storage import CorpusStore
from operator_console.wiring import McpBridge, build_catalogue, seed_operation_classes


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    for lane in ("backlog", "in-progress", "needs-review", "done"):
        (tmp_path / "corpus" / "tickets" / lane).mkdir(parents=True)
    (tmp_path / "corpus" / "gates").mkdir(parents=True)
    (tmp_path / "decisions").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    store = CorpusStore(tmp_path, profile="personal")
    store.ticket_create("cache-concurrency", "Investigate the cache race.")
    store.gate_create("voice-loop", state="needs-review")
    return tmp_path


@pytest_asyncio.fixture
async def bench(corpus_root):
    """Fully wired bench rig over a real stdio MCP session."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "operator_switchboard_mcp",
              "--root", str(corpus_root), "--profile", "personal"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bridge = McpBridge(session)
            registry = SurfaceRegistry(corpus_root)
            opreg = OperationRegistry()
            seed_operation_classes(opreg)
            llm = StubLLM("(tier 3 reached)")
            router = Router(registry=registry, opreg=opreg,
                            machine=ConfirmationMachine(), catalogue=[],
                            llm=llm,
                            turnlog=TurnLog(corpus_root / "logs" / "turns.jsonl"))
            router.catalogue.extend(
                build_catalogue(bridge, registry, router.context))
            yield {"router": router, "llm": llm, "root": corpus_root,
                   "registry": registry, "bridge": bridge}
```

- [ ] **Step 2: Write the eight goal-condition tests**

`tests/acceptance/test_goal_conditions.py`:

```python
"""Phase 0 acceptance — one test per kickoff-spec goal condition."""

import json
import subprocess

import pytest

from operator_router.turnlog import TurnLog


def turn_lines(root):
    return TurnLog(root / "logs" / "turns.jsonl").lines()


async def test_gc1_register_two_kinds_and_resolve(bench):
    r = bench["router"]
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("register chat proxy-pilot at claude://claude.ai/chat/abc")
    await r.handle("confirm register")
    reg = bench["registry"]
    assert reg.resolve("build-box").surface.kind == "tmux"
    assert reg.resolve("proxy pilot").surface.kind == "chat"  # fuzzy spoken


async def test_gc2_switch_is_fastpath_zero_llm(bench):
    r = bench["router"]
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("switch to build-box")
    assert bench["llm"].calls == []
    line = turn_lines(bench["root"])[-1]
    assert line["tier"] == 1


async def test_gc3_ticket_flow_with_commit_trail(bench):
    r = bench["router"]
    assert "cache-concurrency" in await r.handle("list tickets")
    assert "cache race" in await r.handle("read ticket cache-concurrency")
    await r.handle("comment on cache-concurrency: needs a lock audit")
    await r.handle("confirm comment")
    await r.handle("move cache-concurrency to needs-review")
    await r.handle("confirm move")
    t = await bench["bridge"].call("ticket_read", {"name": "cache-concurrency"})
    assert t["lane"] == "needs-review"
    log = subprocess.run(["git", "log", "--format=%s"], cwd=bench["root"],
                         capture_output=True, text=True, check=True).stdout
    assert "ticket_transition" in log and "token=rev" in log
    assert "profile=personal" in log


async def test_gc4_gate_stamp_idempotency(bench):
    r = bench["router"]
    await r.handle("stamp gate voice-loop as approved")
    reply = await r.handle("confirm gate voice-loop")
    assert "revision 1" in reply
    # replay the same token directly against the tool: verified no-op
    replay = await bench["bridge"].call(
        "gate_stamp", {"name": "voice-loop", "state": "approved",
                       "token": "rev0"})
    assert replay["status"] == "already_applied"
    stale = await bench["bridge"].call(
        "gate_stamp", {"name": "voice-loop", "state": "approved",
                       "token": "rev99"})
    assert stale["status"] == "stale_token" and stale["current_revision"] == 1


async def test_gc5_unmatched_reaches_tier3(bench):
    r = bench["router"]
    reply = await r.handle("what changed in the repo overnight?")
    assert reply == "(tier 3 reached)"
    assert turn_lines(bench["root"])[-1]["tier"] == 3


@pytest.mark.skip(reason="goal condition 6 is a manual smoke test against "
                         "Claude Desktop: uv run python "
                         "packages/desktop-adapter/smoke.py")
def test_gc6_desktop_adapter_smoke():
    ...


async def test_gc7_profile_flag_on_every_line_and_record(bench):
    r = bench["router"]
    await r.handle("status")
    await r.handle("register tmux build-box at tmux:main")
    await r.handle("confirm register")
    await r.handle("what is the airspeed of an unladen swallow?")
    root = bench["root"]
    # every turn-log line
    for line in turn_lines(root):
        assert line["profile"] in ("work", "personal")
    # every persisted registry record
    for p in (root / "registry" / "surfaces").glob("*.json"):
        assert json.loads(p.read_text())["profile"] in ("work", "personal")
    # every corpus record
    for p in (root / "corpus").rglob("*.md"):
        assert "profile:" in p.read_text()
    # every switchboard commit
    log = subprocess.run(["git", "log", "--format=%s"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    for line in log.splitlines():
        if line.startswith("switchboard:"):
            assert "profile=" in line


async def test_gc8_unclassified_op_refused_as_class_x(bench):
    import re
    from operator_router.toolrouter import CatalogueEntry

    ran = []

    async def run(m):
        ran.append(1)
        return "poked"

    bench["router"].catalogue.append(CatalogueEntry(
        op_name="poke_prod", label="poke prod",
        pattern=re.compile(r"^poke prod$"), readback=None, run=run,
        token_fetch=None))
    reply = await bench["router"].handle("poke prod")
    assert ran == [] and "confirm poke prod" in reply.lower()
```

- [ ] **Step 3: Add runtime dirs to .gitignore**

Append to `.gitignore`:

```
logs/
registry/
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all green; exactly 1 skipped (gc6, manual by design)

- [ ] **Step 5: Commit**

```bash
git add tests .gitignore
git commit -m "test: acceptance suite for the eight Phase 0 goal conditions"
```

---

## Post-plan notes for the finishing pass

- Goal condition 6 stays manual: run `uv run python packages/desktop-adapter/smoke.py` with Claude Desktop installed and Accessibility granted; record the result in the PR body.
- As-built deltas to record in the decision log at Gate 0 (per kickoff spec): `label_for` dynamic labels, `ClaudeCLI` as tier-3 implementation, ticket file frontmatter format, `already_applied` via `last_applied_token`.
- Run `uv run ruff check packages tests` before the final commit.
