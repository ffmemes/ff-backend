import uuid
from typing import Any

import httpx

from src.config import settings
from src.storage.schemas import OcrResult

HEADERS = {
    "accept": "application/json",
    "Content-Type": "application/octet-stream"
}

async def ocr_modal(
    file_content: bytes,
    language: str = "en",
    endpoint: str = settings.MODAL_ENDPOINT,
) -> dict[str, Any]:

    async with httpx.AsyncClient() as client:
        response = await client.post(
            endpoint,
            params={"lang": language},
            headers=HEADERS,
            data=file_content,
        )
        response.raise_for_status()
        return response.json()


async def ocr_content(content: bytes, language: str = "ru") -> OcrResult | None:
    try:
        ocr_result = await ocr_modal(content, language)
    except Exception as e:
        print(f"Modal OCR error: {e}")
        return None

    if ocr_result is None:
        print(f"Modal OCR returned no result: {ocr_result}.")
        return None

    try:
        # Ensure raw_result is a dictionary
        if isinstance(ocr_result, list):
            raw_result = {"outputs": [{"value": ocr_result}]}
        else:
            raw_result = ocr_result

        # Extract text from list structure
        if isinstance(ocr_result, list):
            full_text = " ".join([r[1] for r in ocr_result if len(r) > 1])
        else:
            rows = ocr_result.get("outputs", [{}])[0].get("value", [])
            full_text = " ".join([r[1] for r in rows if len(r) > 1])

        return OcrResult(
            model="easyocr",
            text=full_text,
            raw_result=raw_result,
        )
    except Exception as e:
        print(f"Error parsing OCR result: {e}")
        return None
