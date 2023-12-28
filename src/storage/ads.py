STOP_WORDS = [
    "читать далее", "теперь в телеграм"
]

def text_is_adverisement(original_text: str) -> bool:
    text = original_text.lower().strip()
    for word in STOP_WORDS:
        if word in text:
            return True
        
    return False