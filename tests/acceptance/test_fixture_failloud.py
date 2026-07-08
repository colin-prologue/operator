import asyncio

import pytest


async def test_setup_failure_surfaces_instead_of_hanging(monkeypatch):
    """The bench fixture's handshake must fail loud when the lifecycle
    task dies before signalling ready."""
    ready = asyncio.Event()

    async def dying_lifecycle():
        raise RuntimeError("boom")

    task = asyncio.create_task(dying_lifecycle())
    ready_waiter = asyncio.create_task(ready.wait())
    done, _ = await asyncio.wait({ready_waiter, task}, timeout=5.0,
                                 return_when=asyncio.FIRST_COMPLETED)
    assert task in done
    ready_waiter.cancel()
    assert isinstance(task.exception(), RuntimeError)
