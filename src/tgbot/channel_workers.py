"""Shared lifecycle for webhook and polling background channel maintenance."""

import asyncio

from telegram import Bot

from src.config import settings
from src.recommendations.channel_hits import run_channel_hit_refresh_worker
from src.tgbot.channel_membership import run_channel_membership_worker


def start_channel_workers(bot: Bot) -> list[asyncio.Task]:
    tasks = []
    if settings.CHANNEL_MEMBERSHIP_SYNC_ENABLED:
        tasks.append(asyncio.create_task(run_channel_membership_worker(bot)))
    if settings.CHANNEL_HITS_ENABLED:
        tasks.append(asyncio.create_task(run_channel_hit_refresh_worker()))
    return tasks


async def stop_channel_workers(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
