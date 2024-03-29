import base64
import html
import logging

from openai import AsyncOpenAI
from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from src.config import settings
from src.storage.upload import download_meme_content_from_tg
from src.tgbot.logs import log


def encode_image_bytes(image: bytes):
    return base64.b64encode(image).decode("utf-8")


async def call_chatgpt_vision(image: bytes, prompt: str) -> str:
    encoded_image = encode_image_bytes(image)

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"},
                    },
                ],
            }
        ],
        max_tokens=300,
    )

    return response.choices[0].message.content


async def explain_meme_ru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Explain a tg channel post to the user
    Handle message from channel in a chat
    """

    file_id = update.message.photo[-1].file_id
    image_bytes = await download_meme_content_from_tg(file_id)
    vision_result = await call_chatgpt_vision(
        image_bytes,
        """
Мама прислала тебе эту смешную картинку. Объясни двумя предложениями, в чем прикол.
Не пересказывай содержание мема и используй неформальную лексику.
        """,
    )

    if vision_result:
        vision_result = html.unescape(vision_result)
        try:
            await update.message.reply_text(vision_result)
        except Forbidden:
            log(
                f"Can't send meme explanation to chat: {vision_result}",
                level=logging.ERROR,
                exc_info=True,
            )
