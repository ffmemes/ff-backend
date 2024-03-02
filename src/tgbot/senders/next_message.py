import asyncio
import logging

from telegram import (
    Message,
    Update,
)

from src.recommendations.meme_queue import check_queue, get_next_meme_for_user
from src.recommendations.service import (
    create_user_meme_reaction,
    user_meme_reaction_exists,
)
from src.tgbot.constants import Reaction
from src.tgbot.senders.achievements import send_achievement_if_needed
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme import (
    edit_last_message_with_meme,
    send_new_message_with_meme,
)
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id


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


async def next_message(
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    # TODO: if watched > 30 memes / day show paywall / tasks / donate

    await send_achievement_if_needed(user_id)

    while True:
        meme = await get_next_meme_for_user(user_id)
        if not meme:
            asyncio.create_task(check_queue(user_id))
            # TODO: also edit / delete
            return await send_queue_preparing_alert(user_id)

        exists = await user_meme_reaction_exists(user_id, meme.id)
        if not exists:  # this meme wasn't sent yet
            break
        else:
            logging.warning(f"User {user_id} already received meme {meme.id}")

    reply_markup = meme_reaction_keyboard(meme.id)
    meme.caption = await get_meme_caption_for_user_id(meme, user_id)

    send_new_message = (
        prev_reaction_id is None or Reaction(prev_reaction_id).is_positive
    )
    if not send_new_message and prev_update_can_be_edited_with_media(prev_update):
        msg = await edit_last_message_with_meme(
            user_id, prev_update.callback_query.message.id, meme, reply_markup
        )
    else:
        msg = await send_new_message_with_meme(user_id, meme, reply_markup)

    await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
    asyncio.create_task(check_queue(user_id))
    return msg
