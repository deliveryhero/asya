"""Translator actor: mock translation by reversing each word."""
from .asya_utils import actor


@actor
def translate(payload: dict) -> dict:
    text = payload.get("text", "")
    target_lang = payload.get("target_lang", "reverse")

    if target_lang == "reverse":
        translated = " ".join(w[::-1] for w in text.split())
    elif target_lang == "upper":
        translated = text.upper()
    elif target_lang == "pig_latin":
        translated = " ".join(
            w[1:] + w[0] + "ay" if w else w for w in text.split()
        )
    else:
        translated = text

    payload["translated"] = translated
    payload["target_lang"] = target_lang
    print(f"[+] translated to {target_lang}: {translated[:50]}")
    return payload
