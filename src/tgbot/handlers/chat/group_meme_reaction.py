import logging

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.database import chat_meme_reaction, execute, fetch_all

logger = logging.getLogger(__name__)

CHAT_MEME_REACTION_CALLBACK_PATTERN = r"^cmr:\d+:[12]$"


def build_meme_reaction_keyboard(
    meme_id: int, likes: int = 0, dislikes: int = 0
) -> InlineKeyboardMarkup:
    like_text = f"👍 {likes}" if likes > 0 else "👍"
    dislike_text = f"👎 {dislikes}" if dislikes > 0 else "👎"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(like_text, callback_data=f"cmr:{meme_id}:1"),
                InlineKeyboardButton(dislike_text, callback_data=f"cmr:{meme_id}:2"),
            ]
        ]
    )


async def get_meme_reaction_counts(chat_id: int, meme_id: int) -> dict[int, int]:
    rows = await fetch_all(
        text(
            """
            SELECT reaction, count(*) AS cnt
            FROM chat_meme_reaction
            WHERE chat_id = :chat_id AND meme_id = :meme_id
            GROUP BY reaction
        """
        ),
        {"chat_id": chat_id, "meme_id": meme_id},
    )
    return {row["reaction"]: row["cnt"] for row in rows}


async def handle_chat_meme_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    # Parse callback: cmr:{meme_id}:{reaction}
    parts = query.data.split(":")
    meme_id = int(parts[1])
    reaction = int(parts[2])

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Upsert: 1 user = 1 vote, allow opinion change
    stmt = (
        insert(chat_meme_reaction)
        .values(
            chat_id=chat_id,
            meme_id=meme_id,
            user_id=user_id,
            reaction=reaction,
        )
        .on_conflict_do_update(
            constraint="uq_chat_meme_reaction",
            set_={"reaction": reaction},
        )
    )
    await execute(stmt)

    # Get updated counts
    counts = await get_meme_reaction_counts(chat_id, meme_id)
    likes = counts.get(1, 0)
    dislikes = counts.get(2, 0)

    # Update button counters
    keyboard = build_meme_reaction_keyboard(meme_id, likes, dislikes)
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except BadRequest:
        pass  # Message too old or already has same markup

    await query.answer()
