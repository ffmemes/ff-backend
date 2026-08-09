import asyncio

from prefect import flow, get_run_logger

from src.broadcasts.service import (
    get_user_ids_active_minutes_ago,
    get_users_active_more_than_days_ago,
)
from src.flows.hooks import notify_telegram_on_failure
from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.tgbot.bot import bot
from src.tgbot.senders.meme import send_meme_to_user

FIRST_MEME_NUDGE_DRAIN_TIMEOUT_SECONDS = 10

_BROADCAST_FLOW_OPTS = dict(
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=600,
    on_failure=[notify_telegram_on_failure],
)


class _FirstMemeNudgeTaskList(list[asyncio.Task[None]]):
    def __init__(self, logger):
        super().__init__()
        self._logger = logger
        self._closed = False
        self._late_observers: set[asyncio.Task[None]] = set()

    def append(self, task: asyncio.Task[None]) -> None:
        if self._closed:
            observer = asyncio.create_task(_observe_first_meme_nudge_task(task, self._logger))
            self._late_observers.add(observer)
            observer.add_done_callback(self._late_observers.discard)
            self._logger.warning(
                "Registered first-meme nudge task after broadcast drain; "
                "observing in-flight send to completion"
            )
            return

        super().append(task)

    def close(self) -> None:
        self._closed = True


async def _send_to_user(
    user_id: int,
    first_meme_nudge_tasks: list[asyncio.Task[None]],
    *,
    broadcast_label: str = "broadcast_reengagement",
) -> None:
    await check_queue(user_id)
    meme = await get_next_meme_for_user(user_id)
    if meme:
        await send_meme_to_user(
            bot,
            user_id,
            meme,
            first_meme_nudge_tasks=first_meme_nudge_tasks,
            # Distinguish retention pushes from in-session feed for analytics
            # (dwell / sec_to_react distributions differ by delivery path).
            recommended_by=broadcast_label,
        )


async def _drain_first_meme_nudge_tasks(
    tasks: list[asyncio.Task[None]],
    logger,
) -> None:
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FIRST_MEME_NUDGE_DRAIN_TIMEOUT_SECONDS

        while tasks:
            current_tasks = list(tasks)
            tasks.clear()
            timeout = max(0, deadline - loop.time())

            if timeout == 0:
                done: set[asyncio.Task[None]] = set()
                pending = set(current_tasks)
            else:
                done, pending = await asyncio.wait(
                    current_tasks,
                    timeout=timeout,
                )

            for task in done:
                _log_first_meme_nudge_task_result(task, logger)

            if pending:
                timed_out_tasks = set(pending)
                timed_out_tasks.update(tasks)
                tasks.clear()
                for task in timed_out_tasks:
                    task.add_done_callback(
                        lambda done_task: _log_first_meme_nudge_task_result(
                            done_task,
                            logger,
                        )
                    )
                logger.warning(
                    "Timed out waiting for %s first-meme nudge(s); left in-flight sends running",
                    len(timed_out_tasks),
                )
                return
    finally:
        close = getattr(tasks, "close", None)
        if close is not None:
            close()


def _log_first_meme_nudge_task_result(task: asyncio.Task[None], logger) -> None:
    if task.cancelled():
        return

    exc = task.exception()
    if exc is not None:
        logger.warning(
            "Failed to send first-meme nudge after broadcast meme delivery",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


async def _observe_first_meme_nudge_task(task: asyncio.Task[None], logger) -> None:
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(
            lambda done_task: _log_first_meme_nudge_task_result(done_task, logger)
        )
        raise
    except Exception:
        pass

    _log_first_meme_nudge_task_result(task, logger)


async def broadcast_next_meme_to_users(user_ids: list[int]):
    logger = get_run_logger()
    logger.info(f"Going to sent next meme to {len(user_ids)} users")

    for user_id in user_ids:
        first_meme_nudge_tasks: list[asyncio.Task[None]] = _FirstMemeNudgeTaskList(logger)
        try:
            await asyncio.wait_for(
                _send_to_user(user_id, first_meme_nudge_tasks),
                timeout=20,
            )
            logger.info(f"Sent meme to #{user_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Timed out processing user #{user_id} (>20s), skipping")
        except Exception:
            logger.warning(f"Failed to send meme to #{user_id}", exc_info=True)
        await _drain_first_meme_nudge_tasks(first_meme_nudge_tasks, logger)
        await asyncio.sleep(0.2)  # flood control


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_15m_ago():
    user_ids = await get_user_ids_active_minutes_ago(15, 30)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_24h_ago():
    user_ids = await get_user_ids_active_minutes_ago(24 * 60, 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_48h_ago():
    user_ids = await get_user_ids_active_minutes_ago(48 * 60, 48 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_1w_ago():
    user_ids = await get_user_ids_active_minutes_ago(7 * 24 * 60, 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_2w_ago():
    user_ids = await get_user_ids_active_minutes_ago(2 * 7 * 24 * 60, 2 * 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_4w_ago():
    user_ids = await get_user_ids_active_minutes_ago(4 * 7 * 24 * 60, 4 * 7 * 24 * 60 + 60)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_more_than_days_ago(days: int = 3):
    """To call manually sometimes"""
    user_ids = await get_users_active_more_than_days_ago(days)
    await broadcast_next_meme_to_users(user_ids)
