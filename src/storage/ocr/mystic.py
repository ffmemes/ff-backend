import logging
import uuid
from typing import Any

import httpx
from httpx import HTTPStatusError, RequestError

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

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
        try:
            response = await client.post(
                "https://www.mystic.ai/v4/files",
                files=files,
                headers=HEADERS,
            )
            response.raise_for_status()
            path = "https://storage.mystic.ai/" + response.json()["path"]
            return path
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
            logging.error(f"Error loading file to Mystic: {str(e)}")
            raise


async def ocr_mystic_file_path(
    mystic_file_path: str,
    language: str,
    pipeline_id: str = PIPELINE_ID,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0)) as client:
        try:
            response = await client.post(
                "https://www.mystic.ai/v4/runs",
                json={
                    "pipeline": pipeline_id,
                    "inputs": [
                        {
                            "type": "file",
                            "file_path": mystic_file_path,
                        },
                        {"type": "string", "value": language},
                    ],
                    "wait_for_resources": True,
                },
                headers=HEADERS,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
            logging.error(f"Error in OCR process: {str(e)}")
            raise


async def ocr_content(content: bytes, language: str) -> OcrResult | dict:
    try:
        mystic_file_path = await load_file_to_mystic(content)
    except (HTTPStatusError, RequestError) as e:
        logging.error(f"Error loading file to Mystic: {str(e)}")
        return {"error": f"Failed to load file: {str(e)}"}

    try:
        ocr_result = await ocr_mystic_file_path(mystic_file_path, language)
    except (HTTPStatusError, RequestError) as e:
        logging.error(f"Error during OCR process: {str(e)}")
        return {
            "error": f"OCR process failed: {str(e)}",
            "mystic_file_path": mystic_file_path,
        }

    if ocr_result is None or ocr_result["outputs"] is None:
        logging.warning("Mystic OCR returned no result")
        return {"error": "Mystic OCR returned no result", "ocr_result": ocr_result}

    rows = ocr_result["outputs"][0]["value"]
    full_text = " ".join([r[1] for r in rows])

    return OcrResult(
        model=f"mystic:{PIPELINE_ID}",
        text=full_text,  # TODO: parse from ocr_result
        raw_result=ocr_result,
    )
