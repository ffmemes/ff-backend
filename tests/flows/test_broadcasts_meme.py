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


@pytest.mark.asyncio
async def test_broadcast_logs_first_meme_nudge_appended_after_drain():
    async def nudge_task() -> None:
        raise RuntimeError("late nudge failed")

    logger = MagicMock()
    tasks = broadcast_meme._FirstMemeNudgeTaskList(logger)

    await broadcast_meme._drain_first_meme_nudge_tasks(tasks, logger)

    task = asyncio.create_task(nudge_task())
    tasks.append(task)
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    logger.warning.assert_any_call(
        "Registered first-meme nudge task after broadcast drain; left in-flight send running"
    )
    assert any(
        call.args == ("Failed to send first-meme nudge after broadcast meme delivery",)
        and "exc_info" in call.kwargs
        for call in logger.warning.call_args_list
    )
