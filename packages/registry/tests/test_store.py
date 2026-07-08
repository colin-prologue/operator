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


def test_rename_to_same_name_is_a_safe_noop(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("proxy-pilot", "chat"))
    result = reg.rename("proxy-pilot", "proxy-pilot")
    assert result.name == "proxy-pilot"
    assert reg.resolve("proxy-pilot").surface is not None


def test_rename_onto_existing_surface_refuses(tmp_path: Path):
    reg = SurfaceRegistry(tmp_path)
    reg.register(make("alpha", "chat"))
    reg.register(make("beta", "tmux"))
    with pytest.raises(ValueError, match="already exists"):
        reg.rename("alpha", "beta")
    # both survive untouched
    assert reg.resolve("alpha").surface.kind == "chat"
    assert reg.resolve("beta").surface.kind == "tmux"
