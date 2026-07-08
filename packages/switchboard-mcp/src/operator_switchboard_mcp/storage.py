from __future__ import annotations

import re
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

    _TOKEN_RE = re.compile(r"^rev\d+$")

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
        if not self._TOKEN_RE.match(token or ""):
            raise StaleTokenError(meta["revision"])
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
