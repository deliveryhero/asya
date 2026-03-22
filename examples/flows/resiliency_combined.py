"""Flow example: combined resiliency — retry, timeout, and error routing.

Demonstrates all three resiliency mechanisms working together:
- @retry(max_attempt_number=5) on fetch_data -> policies.default.maxAttempts: 5
- @timeout(10) on parse_data -> timeout.actor: 10
- asyncio.timeout(60) scoping both -> timeout.actor: 60 (scope-level)
- try/except ValueError -> error routing to handle_bad_data

The sidecar evaluates resiliency config at runtime:
1. Per-execution timeout kills the runtime call if it exceeds the limit
2. Retry policy re-enqueues on failure (up to maxAttempts)
3. Error routing matches exception types and routes to handler actors

Compile with:
    asya compile resiliency_combined.py --output-dir compiled/
"""

import asyncio

from _asya_utils import actor, flow, retry, timeout


@flow
async def data_pipeline(p: dict) -> dict:
    p["status"] = "started"

    async with asyncio.timeout(60):
        try:
            p = await fetch_data(p)
            p = await parse_data(p)
        except ValueError:
            p["error"] = "bad_data"
            p = await handle_bad_data(p)

    p = await store_results(p)
    return p


@actor
@retry(max_attempt_number=5, max_delay=30)
def fetch_data(p: dict) -> dict:
    """Fetch from unreliable API — retries up to 5 times, max 30s total."""
    p["raw_data"] = "fetched"
    return p


@actor
@timeout(10)
def parse_data(p: dict) -> dict:
    """Parse raw data — timeout after 10s per execution."""
    p["parsed"] = True
    return p


@actor
def handle_bad_data(p: dict) -> dict:
    """Handle invalid data — log and substitute defaults."""
    p["parsed"] = False
    p["fallback"] = True
    return p


@actor
def store_results(p: dict) -> dict:
    """Store final results."""
    p["status"] = "completed"
    return p
