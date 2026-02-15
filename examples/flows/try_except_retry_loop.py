"""
Retry loop with try-except.

Retries up to 3 times on ConnectionError, re-raises on ValueError.
Demonstrates combining while loops with try-except for resilient processing.
"""


def retry_pipeline(p: dict) -> dict:
    p["attempt"] = 0
    p = prepare_request(p)
    while p["attempt"] < 3:
        p["attempt"] += 1
        try:
            p = call_external_api(p)
            p = call_another_api(p)
        except ConnectionError:
            p = log_retry(p)
        except ValueError:
            raise
    # p = notify_complete(p)
    return p


def prepare_request(p: dict) -> dict:
    """Validate and prepare the outgoing request."""
    return p


def call_external_api(p: dict) -> dict:
    """Call an external API that may fail."""
    return p


def call_another_api(p: dict) -> dict:
    """Call another API that may fail."""
    return p


def log_retry(p: dict) -> dict:
    """Log the retry attempt."""
    return p


def notify_complete(p: dict) -> dict:
    """Send completion notification."""
    return p
