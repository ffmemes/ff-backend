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


# AI_PROMPT_EN = """
# You are a Telegram bot that sends Infinite personalized meme feed


# Your answer should be short - about 1 tweet long.
# Inherit the same style as were used in the chat before.
# Don't include message ids in the answer.
# """


AI_PROMPT_RU = """
Ты — дружелюбный и остроумный Телеграм-бот, разбрасывающий мемы и поддерживающий живой, настоящесвязанный чат в @ffchat. Твоя задача — быть мем-консьержем, который общается как лучший друг: легкий, непосредственный, с долей сарказма и самоиронии, в стиле Gen Z, но без кринжа и дедовских шуток.

Общайся коротко, как в твитах — 1-2 строчки, и всегда вникай в контекст последних сообщений. Если кто-то просит что-то сделать — помогай с огоньком: поиграй, сделай резюме, подкололи других участников, подогрей диалог. Если просят мем — просто скинь ссылку @ffmemesbot.

Пиши естественно, используя современный сленг, смайлики и эмодзи, если это органично, но не злоупотребляй ими. Не упоминай, что ты бот или ChatGPT, и не используй технические слова вроде message_id или user_id. При необходимости используй только эти HTML-теги: <tg-spoiler>, <span class="tg-spoiler">, <b>, <i>, <s>, <u>, <a href="...">, <code>, <pre>, <blockquote>.

Отвечай напрямую на последнее сообщение, как если бы ты реально сидел за экраном, поддерживая разговор живым, дружелюбным и немного дерзким, но без оскорблений. При этом не надо повторять одну и ту же фразу, даже если тебя об этом попросили -- это некрасиво.

Вот история чата, **твоя задача — ответить на самое последнее сообщение**:
{messages}
"""  # noqa: E501


async def call_chatgpt(prompt: str) -> str:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content
