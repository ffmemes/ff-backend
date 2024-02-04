from src.tgbot.schemas import UserTg


def remove_buttons_with_callback(reply_markup: dict) -> dict:
    original_keyboard = reply_markup["inline_keyboard"]

    new_keyboard = []
    for row in original_keyboard:
        filtered_buttons = []
        for button in row:
            if "callback_data" in button:
                continue

            filtered_buttons.append(button)

        new_keyboard.append(filtered_buttons)

    reply_markup["inline_keyboard"] = new_keyboard
    return reply_markup


def tg_user_repr(tg_user: UserTg) -> str:
    return f"@{tg_user.username}" if tg_user.username else f"#{tg_user.id}"
