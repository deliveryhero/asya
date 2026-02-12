def resource_pipeline(p: dict) -> dict:
    p["status"] = "started"
    try:
        p = acquire_resource(p)
        p = process_with_resource(p)
    except RuntimeError:
        p["status"] = "failed"
        p = handle_failure(p)
    finally:
        p = release_resource(p)
    p = finalize(p)
    return p
