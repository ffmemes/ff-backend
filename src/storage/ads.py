STOP_WORDS = [
    "читать далее", "теперь в телеграм"
]

MENTION_WORDS = [
    "@", "http",
]

def text_is_adverisement(original_text: str) -> bool:
    text = original_text.lower().strip()
    for word in STOP_WORDS:
        if word in text:
            return True
        
    return False


def filter_caption(original_text: str) -> str:
    """ removes links from caption """
    if text_is_adverisement(original_text):
        return ""
    
    for mw in MENTION_WORDS:
        if mw in original_text:
            return ""
    
    return original_text