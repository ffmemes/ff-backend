"""
a command /uploads shows latest uploaded memes with stats:
- views, likes, like%

and total stats across all uploaded memes
"""

from telegram import (
    InputMediaPhoto,
    InputMediaVideo,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.storage.constants import MemeType
from src.tgbot.handlers.upload.service import (
    get_fans_of_user_id,
    get_uploaded_memes_of_user_id,
)
from src.tgbot.user_info import get_user_info


async def handle_uploaded_memes_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows stats for uploaded memes"""
    user_info = await get_user_info(update.effective_user.id)
    lang = user_info["interface_lang"] if user_info else None

    uploaded_memes = await get_uploaded_memes_of_user_id(update.effective_user.id)
    if len(uploaded_memes) == 0:
        await update.message.reply_text(
            localizer.t("upload.no_uploads_yet", lang),
            parse_mode=ParseMode.HTML,
        )
        return

    total_fans = await get_fans_of_user_id(update.effective_user.id)

    total_views = sum(m["nmemes_sent"] for m in uploaded_memes)
    total_likes = sum(m["nlikes"] for m in uploaded_memes)
    total_dislikes = sum(m["ndislikes"] for m in uploaded_memes)
    if total_likes + total_dislikes == 0:
        total_like_prc = 0
    else:
        total_like_prc = round(total_likes * 100.0 / (total_likes + total_dislikes))

    stats_text = localizer.t("upload.stats_header", lang).format(
        n_memes=len(uploaded_memes),
        total_views=total_views,
        total_likes=total_likes,
        total_like_prc=total_like_prc,
        total_fans=total_fans,
    )

    # show stats for last 5 uploads:
    media = []
    for uploaded_meme in uploaded_memes[:5]:
        views = uploaded_meme["nmemes_sent"]
        likes = uploaded_meme["nlikes"]
        dislikes = uploaded_meme["ndislikes"]
        like_prc = round(likes * 100.0 / (likes + dislikes)) if likes + dislikes else 0

        if uploaded_meme["type"] == MemeType.IMAGE:
            media.append(InputMediaPhoto(media=uploaded_meme["telegram_file_id"]))
        else:
            media.append(InputMediaVideo(media=uploaded_meme["telegram_file_id"]))

        stats_text += f"\n▪ {views} - {likes} - {like_prc}%"

    stats_text += "\n\n" + localizer.t("upload.stats_footer", lang)

    await update.message.reply_media_group(
        media=media,
        caption=stats_text,
        parse_mode=ParseMode.HTML,
    )
