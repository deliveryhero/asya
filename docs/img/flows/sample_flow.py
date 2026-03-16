def sample_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["type"] == "A":
        p["branch"] = "A"
        p = handler_type_a(p)
    else:
        p = handler_type_b(p)
        p["branch"] = "B"
    p = handler_finalize(p)
    return p
