import uuid
import httpx
import logging

from src.config import settings
from src.storage.schemas import OcrResult

# URL for the API endpoint
url = 'https://www.mystic.ai/v3/runs'


headers = {
    "accept": "application/json",
    "authorization": f"Bearer {settings.MYSTIC_TOKEN}"
}

PIPELINE_ID = "uriel/easyocr-r:v30"


async def load_file_to_mystic(file_content: bytes) -> str:
    file_name = f"{uuid.uuid4()}.jpg"
    files = { "pfile": (file_name, file_content, "image/jpeg") }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://www.mystic.ai/v3/pipeline_files",
            files=files,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["path"]
    

async def ocr_url_with_mystic(
    content_url: str,
    language: str = "Russian",
) -> OcrResult:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            json={
                "pipeline_id_or_pointer": PIPELINE_ID,
                "async_run": False,
                "input_data": [
                    {
                        "type": "file",
                        "value": "",
                        "file_path": content_url,
                    },
                    {
                        "type": "string",
                        "value": language
                    }
                ]
            },
            headers=headers,
        )
        response.raise_for_status()
        return OcrResult(
            model=f"mystic:{PIPELINE_ID}",
            result=response.json(),
        )


async def ocr_content(
    content: bytes,  # ??
) -> OcrResult:
    file_path = await load_file_to_mystic(content)
    logging.info(f"Loaded file to mystic: {file_path}")

    ocr_result = await ocr_url_with_mystic(file_path)
    logging.info(f"OCR result from Mystic: {ocr_result}")
    print(ocr_result)
    return ocr_result