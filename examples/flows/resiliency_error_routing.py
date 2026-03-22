"""Flow example: error routing with retry and fallback actors.

Demonstrates how try/except in flows creates error routing rules in
actor manifests, combined with @retry for automatic retries before
routing to error handlers.

When call_primary fails:
1. Sidecar retries up to 3 times (from @retry)
2. If all retries exhausted AND error is ConnectionError -> route to fallback
3. If error is ValueError -> route to handle_validation_error (no retry)
4. Any other error -> default retry policy applies

Compile with:
    asya compile resiliency_error_routing.py --output-dir compiled/
"""

from _asya_utils import actor, flow
from tenacity import retry, stop_after_attempt


@flow
async def failover_pipeline(p: dict) -> dict:
    p["status"] = "started"

    try:
        p = await call_primary(p)
    except ConnectionError:
        p["fallback"] = True
        p = await call_fallback(p)
    except ValueError:
        p["error_type"] = "validation"
        p = await handle_validation_error(p)

    p = await finalize(p)
    return p


@actor
@retry(stop=stop_after_attempt(3))
async def call_primary(p: dict) -> dict:
    """Call primary service — retry 3 times before routing to error handler."""
    p["result"] = "primary_response"
    return p


@actor
@retry(stop=stop_after_attempt(2))
async def call_fallback(p: dict) -> dict:
    """Fallback service — retry twice on failure."""
    p["result"] = "fallback_response"
    return p


@actor
def handle_validation_error(p: dict) -> dict:
    """Handle validation errors — no retry, log and continue."""
    p["result"] = "validation_error_handled"
    return p


@actor
def finalize(p: dict) -> dict:
    """Finalize pipeline output."""
    p["status"] = "completed"
    return p
