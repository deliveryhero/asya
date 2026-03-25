from _asya_utils import flow, actor


@flow
def try_except_catch_all(p: dict) -> dict:
    try:
        p = risky_operation(p)
    except ValueError:
        p["error_type"] = "known"
        p = handle_known_error(p)
    except:
        p["error_type"] = "unknown"
        p = handle_unknown_error(p)
    return p


@actor
def risky_operation(p):
    return p


@actor
def handle_known_error(p):
    return p


@actor
def handle_unknown_error(p):
    return p
