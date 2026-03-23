"""Greeter: prepend a greeting to the text."""


def greet(payload: dict) -> dict:
    name = payload.get("name", "world")
    payload["greeting"] = f"Hello, {name}!"
    print(f"[+] greet: {payload['greeting']}")
    return payload
