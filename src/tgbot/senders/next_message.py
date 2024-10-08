import asyncio
import logging

from telegram import (
    Bot,
    Message,
    Update,
)
from telegram.error import BadRequest

from src.recommendations import meme_queue
from src.recommendations.service import (
    create_user_meme_reaction,
    user_meme_reaction_exists,
)
from src.storage.schemas import MemeData
from src.tgbot.constants import Reaction
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme import (
    edit_last_message_with_meme,
    send_new_message_with_meme,
)
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.senders.popups import get_popup_to_send, send_popup
from src.tgbot.user_info import get_user_info


def prev_update_can_be_edited_with_media(prev_update: Update) -> bool:
    if prev_update.callback_query is None:
        return False  # triggered by a message from user

    # user clicked on our message with buttons
    if prev_update.callback_query.message.effective_attachment is None:
        return False  # message without media

    return True  # message from our bot & has media to be replaced


# 1. Хранить какой юзер какое system message получил
# 2. Под каждым system_message - кнопка next_{system_message_id} для логгирования
# 3. Единая функция ответа на сообщение: редактировать или удалить.
# 4. Ачивки не только по числу мемов: по числу лайков, по рандому
# 5. Не нужен таймаут, так как кнопку "следующее сообщение" нажмут, когда прочитают
# 6. Хранить словарь ссылок на разных языках
# 7. Проверить, что ворнинги не попадаются. Будут - плохо, придется оставить доп запрос.
# 8. Дизлайкнули старое сообщение - удалять и присылать новое сообщение


async def get_next_meme_for_user(user_id: int) -> MemeData | None:
    while True:
        meme = await meme_queue.get_next_meme_for_user(user_id)
        if not meme:  # no memes in queue
            await meme_queue.generate_recommendations(user_id, limit=7)
            meme = await meme_queue.get_next_meme_for_user(user_id)
            if not meme:
                return None

        exists = await user_meme_reaction_exists(user_id, meme.id)
        if not exists:  # this meme wasn't sent yet
            return meme
        else:
            logging.warning(f"User {user_id} already received meme {meme.id}")


async def next_message(
    bot: Bot,
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    user_info = await get_user_info(user_id)
    # TODO: if watched > 30 memes / day show paywall / tasks / donate

    popup = await get_popup_to_send(user_id, user_info)
    if popup:
        return await send_popup(user_id, popup)

    meme = await get_next_meme_for_user(user_id)
    if not meme:
        asyncio.create_task(meme_queue.check_queue(user_id))
        # TODO: also edit / delete previous message
        return await send_queue_preparing_alert(bot, user_id)

    reply_markup = meme_reaction_keyboard(meme.id, user_id)
    meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

    send_new_message = (
        prev_reaction_id is None or Reaction(prev_reaction_id).is_positive
    )
    if not send_new_message and prev_update_can_be_edited_with_media(prev_update):
        try:
            msg = await edit_last_message_with_meme(
                prev_update.callback_query.message, meme, reply_markup
            )
        except BadRequest as e:
            logging.error(f"Failed to edit message: {e}")
            msg = await send_new_message_with_meme(bot, user_id, meme, reply_markup)

    else:
        msg = await send_new_message_with_meme(bot, user_id, meme, reply_markup)

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    asyncio.create_task(meme_queue.check_queue(user_id))
    return msg
