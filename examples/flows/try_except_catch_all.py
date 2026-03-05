def resilient_pipeline(p: dict) -> dict:
    try:
        p = risky_operation(p)
    except ValueError:
        p["error_type"] = "known"
        p = handle_known_error(p)
    except:
        p["error_type"] = "unknown"
        p = handle_unknown_error(p)
    return p


def risky_operation(p):
    return p

def handle_known_error(p):
    return p

def handle_unknown_error(p):
    return p
