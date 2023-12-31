STOP_WORDS = [
    "читать далее", "теперь в телеграм"
]

MENTION_WORDS = [
    "@", "http",
]

def text_is_adverisement(original_text: str | None) -> bool:
    if original_text is None:
        return False
    
    text = original_text.lower().strip()
    for word in STOP_WORDS:
        if word in text:
            return True
        
    return False


def filter_caption(original_text: str | None) -> str | None:
    """ removes links from caption """
    if original_text is None:
        return None

    if text_is_adverisement(original_text):
        return None
    
    for mw in MENTION_WORDS:
        if mw in original_text:
            return None
    
    return original_text