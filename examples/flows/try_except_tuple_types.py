"""
Try-except with tuple exception types.

Catches multiple exception types in a single handler using tuple syntax.
The compiler generates a single retryRule with multiple error entries.
"""

from _asya_utils import flow


@flow
def ingestion_pipeline(p: dict) -> dict:
    try:
        p = fetch_data(p)
        p = parse_data(p)
    except (ConnectionError, TimeoutError):
        p["retry_reason"] = "transient"
        p = queue_for_retry(p)
    except (ValueError, KeyError):
        p["status"] = "bad_input"
        p = reject_input(p)
    return p
