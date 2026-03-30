import logging

from agents import RunContextWrapper, function_tool
from sqlalchemy import text

from src.database import fetch_all, fetch_one

logger = logging.getLogger(__name__)


def get_tools() -> list:
    """Return the list of tools available to the chat agent."""
    return [search_memes, send_meme, get_chat_history]


@function_tool(strict_mode=False)
async def search_memes(
    ctx: RunContextWrapper,
    query: str,
    limit: int = 5,
) -> str:
    """Search memes by text query. Returns matching memes with ID, type, and preview."""
    query = query[:100]
    # Escape ILIKE wildcards to prevent pattern abuse
    query = query.replace("%", r"\%").replace("_", r"\_")
    limit = min(limit, 10)
    rows = await fetch_all(
        text(
            """
            SELECT m.id, m.type,
                   COALESCE(
                       m.ocr_result->>'description',
                       m.ocr_result->>'text', ''
                   ) AS text_preview,
                   COALESCE(ms.nlikes, 0) AS nlikes
            FROM meme m
            LEFT JOIN meme_stats ms ON ms.meme_id = m.id
            WHERE m.status = 'ok'
              AND m.telegram_file_id IS NOT NULL
              AND (
                m.ocr_result->>'text' ILIKE :pattern
                OR m.ocr_result->>'description' ILIKE :pattern
              )
            ORDER BY COALESCE(ms.nlikes, 0) DESC
            LIMIT :limit
        """
        ),
        {"pattern": f"%{query}%", "limit": limit},
    )
    if not rows:
        return "No memes found matching that query."
    lines = []
    for r in rows:
        preview = (r["text_preview"] or "")[:80]
        lines.append(f"ID:{r['id']} ({r['type']}, {r['nlikes']} likes) - {preview}")
    return "\n".join(lines)


@function_tool(strict_mode=False)
async def send_meme(ctx: RunContextWrapper, meme_id: int) -> str:
    """Send a meme to the chat by its ID. Use after search_memes to pick one."""
    context = ctx.context
    try:
        meme_id = int(meme_id)
    except (ValueError, TypeError):
        return f"Invalid meme_id {meme_id!r}: must be an integer."
    meme = await fetch_one(
        text(
            "SELECT id, type, telegram_file_id, caption "
            "FROM meme WHERE id = :meme_id AND status = 'ok'"
        ),
        {"meme_id": meme_id},
    )
    if not meme:
        return f"Meme {meme_id} not found."

    from src.tgbot.handlers.chat.group_meme_reaction import build_meme_reaction_keyboard

    keyboard = build_meme_reaction_keyboard(meme_id)
    file_id = meme["telegram_file_id"]
    meme_type = meme["type"]

    try:
        if meme_type == "animation":
            await context.bot.send_animation(
                chat_id=context.chat_id,
                animation=file_id,
                reply_markup=keyboard,
                reply_to_message_id=context.reply_to_message_id,
            )
        elif meme_type == "video":
            await context.bot.send_video(
                chat_id=context.chat_id,
                video=file_id,
                reply_markup=keyboard,
                reply_to_message_id=context.reply_to_message_id,
            )
        else:
            await context.bot.send_photo(
                chat_id=context.chat_id,
                photo=file_id,
                reply_markup=keyboard,
                reply_to_message_id=context.reply_to_message_id,
            )
        return f"Sent meme {meme_id}."
    except Exception as e:
        return f"Failed to send meme: {e}"


@function_tool(strict_mode=False)
async def get_chat_history(ctx: RunContextWrapper, limit: int = 50) -> str:
    """Fetch more messages from the current chat for additional context."""
    context = ctx.context
    limit = min(limit, 100)
    from src.tgbot.handlers.chat.ai import _messages_to_text
    from src.tgbot.handlers.chat.service import get_latest_chat_messages

    messages = await get_latest_chat_messages(chat_id=context.chat_id, limit=limit)
    return _messages_to_text(messages)
