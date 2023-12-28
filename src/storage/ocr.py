from src.storage.schemas import OcrResult


async def ocr_meme_content(
    content: bytes,  # ??
) -> OcrResult:
    # TODO: call OCR API
    return OcrResult(
        model="mock",
        result={"text": "mock"},
    )