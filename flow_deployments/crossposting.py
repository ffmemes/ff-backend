from pathlib import Path

from prefect.client.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.crossposting.meme import (
    post_meme_to_tgchannelen,
    post_meme_to_tgchannelru,
)

deployment_crossposting_tgchannelru = post_meme_to_tgchannelru.from_source(
    source=str(Path(__file__).parent.parent),
    entrypoint="src/flows/crossposting/meme.py:post_meme_to_tgchannelru",
).deploy(
    name="post_meme_to_tgchannelru",
    schedules=[CronSchedule(cron="20 8,10,12,14,16,18 * * *", timezone="Europe/Moscow")],
    work_pool_name=settings.ENVIRONMENT,
)


deployment_crossposting_tgchannelen = post_meme_to_tgchannelen.from_source(
    source=str(Path(__file__).parent.parent),
    entrypoint="src/flows/crossposting/meme.py:post_meme_to_tgchannelen",
).deploy(
    name="post_meme_to_tgchannelen",
    schedules=[CronSchedule(cron="40 8,10,14,18,20 * * *", timezone="Europe/Moscow")],
    work_pool_name=settings.ENVIRONMENT,
)
