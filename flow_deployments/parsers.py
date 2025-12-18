from pathlib import Path
from prefect.client.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.parsers.ig import parse_ig_sources
from src.flows.parsers.tg import parse_telegram_sources
from src.flows.parsers.vk import parse_vk_sources

deployment_tg = parse_telegram_sources.from_source(
    source=str(Path(__file__).parent.parent),
    entrypoint="src/flows/parsers/tg.py:parse_telegram_sources",
).deploy(
    name="parse_telegram_sources",
    schedules=[CronSchedule(cron="40 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_vk = parse_vk_sources.from_source(
    source=str(Path(__file__).parent.parent),
    entrypoint="src/flows/parsers/vk.py:parse_vk_sources",
).deploy(
    name="parse_vk_sources",
    schedules=[CronSchedule(cron="20 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_ig = parse_ig_sources.from_source(
    source=str(Path(__file__).parent.parent),
    entrypoint="src/flows/parsers/ig.py:parse_ig_sources",
).deploy(
    name="parse_ig_sources",
    schedules=[CronSchedule(cron="30 0 * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)
