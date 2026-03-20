def tokenize(text: str) -> list[str]:
    return text.lower().split()

def word_count(text: str) -> int:
    return len(tokenize(text))
