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

# Patterns in outlink URLs that indicate an ad
AD_LINK_PATTERNS = ["erid=", "utm_campaign="]


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


def outlinks_are_ad(out_links: list[str] | None) -> bool:
    """Check if outlinks contain ad-related patterns (e.g. erid= tracking)."""
    if not out_links:
        return False
    for link in out_links:
        link_lower = link.lower()
        for pattern in AD_LINK_PATTERNS:
            if pattern in link_lower:
                return True
    return False


def post_is_likely_ad(
    caption: str | None,
    out_links: list[str] | None,
    views: int,
    median_views: float | None,
) -> bool:
    """Detect ads using engagement signals on top of text analysis.

    A post is likely an ad if it has external links AND below-median views.
    Ad posts typically get less organic engagement than regular content.
    """
    if text_is_adverisement(caption):
        return True

    if outlinks_are_ad(out_links):
        return True

    has_outlinks = bool(out_links and len(out_links) > 0)
    if not has_outlinks:
        return False

    # Outlinks + below-median views = strong ad signal
    if median_views and views > 0 and views < median_views * 0.5:
        return True

    # Outlinks + long caption = likely sponsored content
    if caption and len(caption.strip()) > 100 and has_outlinks:
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
