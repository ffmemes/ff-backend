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


# TODO: make User schema
def format_user_to_str(user_id: int, username: str | None) -> str:
    return f"@{username}" if username else f"#{user_id}"
