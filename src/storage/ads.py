STOP_WORDS = [
    "читать далее",
    "теперь в телеграм",
    "t.me/",
    "перейти",
    "подписы",
    "https://t.me/",
    "источник",
    "фулл",
    "без цензуры",
    "секс",
    "порно",
    "18+",
    "onlyfans",
    "erid",
    "реклама",
    "телега",
    "баян",
    "подписот",
]

MENTION_WORDS = ["@", "http", "t.me/"]


def text_is_adverisement(original_text: str | None) -> bool:
    if original_text is None:
        return False

    text = original_text.lower().strip()

    # memes usually have short captions
    if len(text) > 200:
        return True

    for word in STOP_WORDS:
        if word in text:
            return True

    return False


def filter_caption(original_text: str | None) -> str | None:
    """removes links from caption"""
    if original_text is None:
        return None

    if text_is_adverisement(original_text):
        return None

    for mw in MENTION_WORDS:
        if mw in original_text:
            return None

    return original_text
