import base64

from openai import AsyncOpenAI

from src.config import settings


def encode_image_bytes(image: bytes):
    return base64.b64encode(image).decode("utf-8")


async def call_chatgpt_vision(image: bytes, prompt: str) -> str:
    encoded_image = encode_image_bytes(image)

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model="gpt-4o",
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


def _messages_to_text(messages: list[dict]) -> str:
    """message_id, date, user_id, text, reply_to_message_id, username, first_name"""

    messages = sorted(messages, key=lambda x: x["date"])

    text = ""
    for m in messages:
        msg_text = m["text"] or "[media]"
        header = f"""FROM: {m["from_name"]}"""
        if m["reply_to_name"]:
            header += f""", Reply To: {m["reply_to_name"]}"""

        message_text = f"""
{header}
{msg_text}
        """

        text += message_text.strip() + "\n"

    return text
