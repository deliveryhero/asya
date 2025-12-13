
def conditional_nested_flow(p: dict) -> dict:
    p = handler_validate_input(p)

    p["x"] = 1
    if p["a"] == "A":
        p["x"] += 1
        p = handler_a(p)
        if p["x"] > 2:
            p = handler_b(p)
            p["x"] += 2
            if p["x"] > 2:
                p["x"] += 3
                p = handler_b(p)
                p["x"] += 4
            else:
                p["x"] += 5
                p = handler_c(p)
        else:
            p["x"] += 6
            p = handler_d(p)
            p["x"] += 7

    p["x"] += 8
    p = handler_finalize(p)
    p["x"] += 9
    p["x"] *= 10
    return p


def handler_validate_input(p: dict) -> dict:
    ...
    return p


def handler_a(p: dict) -> dict:
    ...
    return p


def handler_b(p: dict) -> dict:
    ...
    return p


def handler_c(p: dict) -> dict:
    ...
    return p

def handler_d(p: dict) -> dict:
    ...
    return p


def handler_finalize(p: dict) -> dict:
    ...
    return p
