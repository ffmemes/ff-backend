STOP_WORDS = [
    # Russian ads / promos
    "читать далее",
    "теперь в телеграм",
    "t.me/",
    "vk",
    "₽",
    "зараб",
    "выплат",
    "дарит",
    "подарок",
    "клик",
    "ooo",
    "ооо",
    "инн",
    "перейти",
    "источник",
    "фулл",
    "без цензуры",
    "секс",
    "порн",
    "xxx",
    "ххх",
    "porn",
    "18+",
    "onlyfans",
    "erid",
    "реклама",
    "телега",
    "баян",
    "подписы",
    "подписот",
    "подписат",
    "notcoin",
    "канал",
    "ссылк",
    "промокод",
    "депозит",
    "халява",
    "разыгрыв",
    "giveaway",
    "чат-бот",
    "заход",
    "crypto",
    "тинькофф",
    "сбербанк",
    "channel",
    "казино",
    "кэшбэк",
    "кешбэк",
    "узнай подробнее",
    "узнать подробнее",
    "бесплатн",
    # English ads / movie piracy / NSFW
    "download movie",
    "download film",
    "click here",
    "1080p",
    "720p",
    "fast link",
    "nude",
    "naked",
    "comment in ->",
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
