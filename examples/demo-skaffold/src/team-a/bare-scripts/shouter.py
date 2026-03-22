"""Shouter: uppercase all text fields."""


def shout(payload: dict) -> dict:  # asya: actor
    for key in ("text", "greeting", "summary"):
        if key in payload:
            payload[key] = payload[key].upper()
    print(f"[+] shout: uppercased {list(payload.keys())}")
    return payload
