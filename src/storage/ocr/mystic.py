import uuid
from typing import Any

import httpx
from prefect import get_run_logger

from src.config import settings
from src.storage.schemas import OcrResult

HEADERS = {
    "accept": "application/json",
    "authorization": f"Bearer {settings.MYSTIC_TOKEN}",
}

PIPELINE_ID = "uriel/easyocr-r:v31"


async def load_file_to_mystic(file_content: bytes) -> str:
    file_name = f"{uuid.uuid4()}.jpg"
    files = {"pfile": (file_name, file_content, "image/jpeg")}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.mystic.ai/v4/files",
            files=files,
            headers=HEADERS,
        )
        response.raise_for_status()
        # Concatenating as v4 just returns starting with /pipeline_files
        path = "https://storage.mystic.ai/" + response.json()["path"]
        return path


async def ocr_mystic_file_path(
    mystic_file_path: str,
    language: str,
    pipeline_id: str = PIPELINE_ID,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.mystic.ai/v4/runs",
            json={
                "pipeline": pipeline_id,
                # Removed as not required now
                # "async_run": False,
                "inputs": [
                    {
                        "type": "file",
                        "file_path": mystic_file_path,
                    },
                    {"type": "string", "value": language},
                ],
            },
            headers=HEADERS,
        )
        response.raise_for_status()
        return response.json()


async def ocr_content(content: bytes, language: str) -> OcrResult | None:
    logger = get_run_logger()
    try:
        mystic_file_path = await load_file_to_mystic(content)
        ocr_result = await ocr_mystic_file_path(mystic_file_path, language)
    except Exception as e:
        logger.exception(msg=f"Mystic OCR error: {e}", exc_info=e)
        return None

    if ocr_result is None or ocr_result["outputs"] is None:
        logger.warning(
            f"Mystic OCR returned no result: {ocr_result}."
        )
        return None

    rows = ocr_result["outputs"][0]["value"]
    full_text = " ".join([r[1] for r in rows])

    return OcrResult(
        model=f"mystic:{PIPELINE_ID}",
        text=full_text,  # TODO: parse from ocr_result
        raw_result=ocr_result,
    )
