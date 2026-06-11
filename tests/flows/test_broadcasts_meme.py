import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.flows.broadcasts import meme as broadcast_meme


@pytest.mark.asyncio
async def test_broadcast_drains_deferred_first_meme_nudge(monkeypatch):
    nudge_started = asyncio.Event()
    nudge_can_finish = asyncio.Event()

    async def nudge_task() -> None:
        nudge_started.set()
        await nudge_can_finish.wait()

    async def send_to_user(_user_id: int, first_meme_nudge_tasks: list[asyncio.Task[None]]) -> None:
        first_meme_nudge_tasks.append(asyncio.create_task(nudge_task()))

    logger = MagicMock()
    monkeypatch.setattr(broadcast_meme, "get_run_logger", lambda: logger)
    monkeypatch.setattr(broadcast_meme, "_send_to_user", send_to_user)
    monkeypatch.setattr(broadcast_meme.asyncio, "sleep", AsyncMock())

    broadcast_task = asyncio.create_task(broadcast_meme.broadcast_next_meme_to_users([12001]))
    await nudge_started.wait()
    await asyncio.sleep(0)

    assert not broadcast_task.done()

    nudge_can_finish.set()
    await asyncio.wait_for(broadcast_task, timeout=0.2)
    logger.info.assert_any_call("Sent meme to #12001")


@pytest.mark.asyncio
async def test_broadcast_drain_timeout_keeps_first_meme_nudge_lease(monkeypatch):
    async def nudge_task() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(nudge_task())
    logger = MagicMock()
    monkeypatch.setattr(broadcast_meme, "FIRST_MEME_NUDGE_DRAIN_TIMEOUT_SECONDS", 0.001)

    await broadcast_meme._drain_first_meme_nudge_tasks([task], logger)

    assert not task.done()
    logger.warning.assert_called_once_with(
        "Timed out waiting for %s first-meme nudge(s); left in-flight sends running",
        1,
    )
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
