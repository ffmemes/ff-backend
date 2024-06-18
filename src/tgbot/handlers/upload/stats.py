"""
    a command /uploads shows latest uploaded memes with stats:
    - views, likes, like%

    and total stats across all uploaded memes
"""


from telegram import (
    InputMediaPhoto,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.tgbot.handlers.upload.service import (
    get_fans_of_user_id,
    get_uploaded_memes_of_user_id,
)


async def handle_uploaded_memes_stats(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Shows stats for uploaded memes"""
    # user_info = await get_user_info(update.effective_user.id)

    uploaded_memes = await get_uploaded_memes_of_user_id(update.effective_user.id)
    if len(uploaded_memes) == 0:
        await update.message.reply_text(
            """
📭 <b>You haven't uploaded any memes yet!</b>

Just forward a meme to our bot to upload it. Only pics are supported yet.

<i>read more:</i> /kitchen
            """,
            parse_mode=ParseMode.HTML,
        )
        return

    total_fans = await get_fans_of_user_id(update.effective_user.id)

    total_views = sum(m["nmemes_sent"] for m in uploaded_memes)
    total_likes = sum(m["nlikes"] for m in uploaded_memes)
    total_dislikes = sum(m["ndislikes"] for m in uploaded_memes)
    total_like_prc = round(total_likes * 100.0 / (total_likes + total_dislikes))

    STATS_TEXT = f"""
<b>YOUR UPLOADED MEMES</b>

📥 You uploaded <b>{len(uploaded_memes)}</b> memes
👁️ Views: <b>{total_views}</b>
👍 Likes: <b>{total_likes}</b>
♥️ Like %: <b>{total_like_prc}%</b>
🙋 Fans: <b>{total_fans}</b>

<b>Latest uploads</b>
views - likes - like %"""

    # show stats for last 5 uploads:
    media = []
    for uploaded_meme in uploaded_memes[:5]:
        views = uploaded_meme["nmemes_sent"]
        likes = uploaded_meme["nlikes"]
        dislikes = uploaded_meme["ndislikes"]
        like_prc = round(likes * 100.0 / (likes + dislikes))

        media.append(InputMediaPhoto(media=uploaded_meme["telegram_file_id"]))

        STATS_TEXT += f"\n▪ {views} - {likes} - {like_prc}%"

    STATS_TEXT += "\n\n<b>Upload more memes and win lots of 🍔</b> /kitchen"
    STATS_TEXT += "\n/leaderboard /stats /balance"

    await update.message.reply_media_group(
        media=media,
        caption=STATS_TEXT,
        parse_mode=ParseMode.HTML,
    )
