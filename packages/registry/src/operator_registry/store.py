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
