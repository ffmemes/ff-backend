import uuid
import httpx
from typing import Any

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

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.mystic.ai/v3/pipeline_files",
            files=files,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()["path"]
    

async def ocr_mystic_file_path(
    mystic_file_path: str,
    pipeline_id: str = PIPELINE_ID,
    language: str = "Russian",
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "pipeline_id_or_pointer": pipeline_id,
                "async_run": False,
                "input_data": [
                    {
                        "type": "file",
                        "value": "",
                        "file_path": mystic_file_path,
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
        return response.json()


async def ocr_content(
    content: bytes,  # ??
) -> OcrResult | None:
    try:
        mystic_file_path = await load_file_to_mystic(content)
        ocr_result = await ocr_mystic_file_path(mystic_file_path)
    except Exception as e:
        print(f"Mystic OCR error: {e}")
        return None
    
    print(f"OCR result from Mystic: {ocr_result}")
    result = ocr_result["result"]
    if result is None:
        print(f"Mystic OCR returned no result: {ocr_result}.")
        return None

    rows = result["outputs"][0]["value"]
    full_text = "\n".join([r[1] for r in rows])

    return OcrResult(
        model=f"mystic:{PIPELINE_ID}",
        text=full_text,  # TODO: parse from ocr_result
        raw_result=ocr_result,
    )