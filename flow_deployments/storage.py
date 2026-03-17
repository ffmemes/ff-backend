from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from src.config import settings
from src.flows.storage.describe_memes import describe_memes_flow
from src.flows.storage.memes import ocr_uploaded_memes

if settings.OCR_ENABLED:
    deployment_ocr_uploaded_memes = Deployment.build_from_flow(
        flow=ocr_uploaded_memes,
        name="OCR Uploaded Memes",
        schedules=[CronSchedule(cron="*/5 * * * *", timezone="Europe/London")],
        work_pool_name=settings.ENVIRONMENT,
    )

    deployment_ocr_uploaded_memes.apply()
else:
    print(
        "Skipping Prefect deployment for OCR Uploaded Memes because OCR is disabled. "
        "Set OCR_ENABLED=true to deploy the OCR flow."
    )

# Describe memes with OpenRouter vision models (runs regardless of OCR_ENABLED)
if settings.OPENROUTER_API_KEY:
    deployment_describe_memes = Deployment.build_from_flow(
        flow=describe_memes_flow,
        name="Describe Memes (OpenRouter Vision)",
        schedules=[CronSchedule(cron="*/30 * * * *", timezone="Europe/London")],
        work_pool_name=settings.ENVIRONMENT,
    )

    deployment_describe_memes.apply()
else:
    print("Skipping Prefect deployment for Describe Memes because OPENROUTER_API_KEY is not set.")
