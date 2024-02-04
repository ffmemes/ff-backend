from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.storage.memes import ocr_uploaded_memes

deployment_ocr_uploaded_memes = Deployment.build_from_flow(
    flow=ocr_uploaded_memes,
    name="OCR Uploaded Memes",
    schedule=(CronSchedule(cron="*/5 * * * *", timezone="Europe/London")),
    work_pool_name=settings.ENVIRONMENT,
)

deployment_ocr_uploaded_memes.apply()
