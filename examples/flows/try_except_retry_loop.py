"""
Retry loop with try-except.

Retries up to 3 times on ConnectionError, re-raises on ValueError.
Demonstrates combining while loops with try-except for resilient processing.
"""

from _asya_utils import actor, flow


@flow
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


@actor
def prepare_request(p: dict) -> dict:
    """Validate and prepare the outgoing request."""
    return p


@actor
def call_external_api(p: dict) -> dict:
    """Call an external API that may fail."""
    return p


@actor
def call_another_api(p: dict) -> dict:
    """Call another API that may fail."""
    return p


@actor
def log_retry(p: dict) -> dict:
    """Log the retry attempt."""
    return p


@actor
def notify_complete(p: dict) -> dict:
    """Send completion notification."""
    return p
