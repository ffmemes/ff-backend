import logging

from sqlalchemy import text

from src.database import fetch_all, fetch_one

logger = logging.getLogger(__name__)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_memes",
            "description": "Search memes by text query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords from the meme text",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_meme",
            "description": "Send a meme to the chat by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meme_id": {
                        "type": "integer",
                        "description": "The meme ID to send",
                    }
                },
                "required": ["meme_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_history",
            "description": "Fetch more messages from the current chat for additional context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of messages to fetch (max 100)",
                        "default": 50,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "react_to_message",
            "description": "React to a message with an emoji.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "integer",
                        "description": "Message ID to react to",
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to react with",
                    },
                },
                "required": ["message_id", "emoji"],
            },
        },
    },
]


async def execute_search_memes(query: str, limit: int = 5) -> str:
    query = query[:100]
    # Escape ILIKE wildcards to prevent pattern abuse
    query = query.replace("%", r"\%").replace("_", r"\_")
    limit = min(limit, 10)
    rows = await fetch_all(
        text("""
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
        """),
        {"pattern": f"%{query}%", "limit": limit},
    )
    if not rows:
        return "No memes found matching that query."
    lines = []
    for r in rows:
        preview = (r["text_preview"] or "")[:80]
        lines.append(f"ID:{r['id']} ({r['type']}, {r['nlikes']} likes) - {preview}")
    return "\n".join(lines)


async def execute_send_meme(
    bot, chat_id: int, meme_id: int | str, reply_to_message_id: int | None = None
) -> str:
    meme_id = int(meme_id)
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
            await bot.send_animation(
                chat_id=chat_id, animation=file_id,
                reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
        elif meme_type == "video":
            await bot.send_video(
                chat_id=chat_id, video=file_id,
                reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
        else:
            await bot.send_photo(
                chat_id=chat_id, photo=file_id,
                reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
        return f"Sent meme {meme_id}."
    except Exception as e:
        return f"Failed to send meme: {e}"


async def execute_get_chat_history(chat_id: int, limit: int = 50) -> str:
    limit = min(limit, 100)
    from src.tgbot.handlers.chat.ai import _messages_to_text
    from src.tgbot.handlers.chat.service import get_latest_chat_messages

    messages = await get_latest_chat_messages(chat_id=chat_id, limit=limit)
    return _messages_to_text(messages)


async def execute_react_to_message(
    bot, chat_id: int, message_id: int, emoji: str
) -> str:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
        )
        return f"Reacted with {emoji}"
    except Exception as e:
        return f"Failed to react: {e}"


async def dispatch_tool(
    tool_name: str,
    args: dict,
    bot,
    chat_id: int,
    reply_to_message_id: int | None = None,
) -> str:
    try:
        if tool_name == "search_memes":
            return await execute_search_memes(
                query=args.get("query", ""),
                limit=args.get("limit", 5),
            )
        elif tool_name == "send_meme":
            return await execute_send_meme(
                bot, chat_id,
                meme_id=args.get("meme_id", 0),
                reply_to_message_id=reply_to_message_id,
            )
        elif tool_name == "get_chat_history":
            return await execute_get_chat_history(
                chat_id,
                limit=args.get("limit", 50),
            )
        elif tool_name == "react_to_message":
            return await execute_react_to_message(
                bot, chat_id,
                message_id=args.get("message_id", 0),
                emoji=args.get("emoji", "👍"),
            )
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error("Tool %s failed: %s", tool_name, e)
        return f"Tool error: {e}"
