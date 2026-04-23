"""
Bare-script flow using # asya: flow comment instead of @flow decorator.

For scripts that don't import any asya utilities — the compiler detects
the flow function via the inline comment directive on the def line.
Actors are also marked with # asya: actor comments.
"""


def greet(p: dict) -> dict:  # asya: actor
    """Add a greeting based on the name field."""
    name = p.get("name", "world")
    p["greeting"] = f"Hello, {name}!"
    return p


def shout(p: dict) -> dict:  # asya: actor
    """Uppercase all string values."""
    for key, val in p.items():
        if isinstance(val, str):
            p[key] = val.upper()
    return p


def bare_script_flow(p: dict) -> dict:  # asya: flow
    p = greet(p)  # asya: actor
    p = shout(p)  # asya: actor
    return p
