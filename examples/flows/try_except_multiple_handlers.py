def data_pipeline(p: dict) -> dict:
    try:
        p = parse_input(p)
        p = transform_data(p)
    except ValueError:
        p["error_type"] = "validation"
        p = handle_validation_error(p)
    except TypeError:
        p["error_type"] = "type_mismatch"
        p = handle_type_error(p)
    except RuntimeError:
        p["error_type"] = "runtime"
        p = handle_runtime_error(p)
    return p
