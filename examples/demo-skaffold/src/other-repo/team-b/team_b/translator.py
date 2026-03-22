"""Translator: mock translation by reversing each word."""


def translate(payload: dict) -> dict:  # asya: actor
    text = payload.get("text", "")
    target = payload.get("target_lang", "reverse")
    if target == "upper":
        payload["translated"] = text.upper()
    elif target == "pig_latin":
        payload["translated"] = " ".join(w[1:] + w[0] + "ay" for w in text.split())
    else:
        payload["translated"] = " ".join(w[::-1] for w in text.split())
    print(f"[+] translate ({target}): {payload['translated'][:40]}")
    return payload
