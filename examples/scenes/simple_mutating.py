

def simple_mutating_scene(p: dict) -> dict:
    p = actor0(p)

    p["k"] = 1
    p = actor1(p)

    p["k"] = 2
    p = actor2(p)

    p["k"] = 3
    p = actor3(p)

    return p



def actor0(p: dict) -> dict:
    return p


def actor1(p: dict) -> dict:
    p["k"] *= 10
    return p

def actor2(p: dict) -> dict:
    p["k"] *= 100
    return p

def actor3(p: dict) -> dict:
    p["k"] *= 1000
    return p
