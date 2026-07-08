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
