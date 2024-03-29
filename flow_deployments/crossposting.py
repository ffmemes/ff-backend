from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.crossposting.meme import (
    post_meme_to_tgchannelen,
    post_meme_to_tgchannelru,
)

deployment_crossposting_tgchannelen = Deployment.build_from_flow(
    flow=post_meme_to_tgchannelen,
    name="post_meme_to_tgchannelen",
    schedule=(CronSchedule(cron="3 */4 * * *", timezone="Europe/London")),
    work_pool_name=settings.ENVIRONMENT,
)

deployment_crossposting_tgchannelen.apply()


deployment_crossposting_tgchannelru = Deployment.build_from_flow(
    flow=post_meme_to_tgchannelru,
    name="post_meme_to_tgchannelru",
    schedule=(CronSchedule(cron="33 */4 * * *", timezone="Europe/London")),
    work_pool_name=settings.ENVIRONMENT,
)

deployment_crossposting_tgchannelru.apply()
