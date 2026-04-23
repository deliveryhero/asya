"""Flow example: combined resiliency — retry, timeout, and error routing.

Demonstrates all three resiliency mechanisms working together:
- @retry(stop=stop_after_attempt(5) | stop_after_delay(30)) on fetch_data
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
import random

from tenacity import retry, stop_after_attempt, stop_after_delay
from timeout_decorator import timeout

from _asya_utils import actor, flow


@flow
async def resiliency_combined(p: dict) -> dict:
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
@retry(stop=stop_after_attempt(5) | stop_after_delay(30))
def fetch_data(p: dict) -> dict:
    """Fetch from unreliable API — retries up to 5 times, max 30s total.

    Simulates flaky API (~40% failure rate).
    """
    if random.random() < 0.4:
        raise ConnectionError("simulated API failure")
    p["raw_data"] = "fetched"
    return p


@actor
@timeout(10)
def parse_data(p: dict) -> dict:
    """Parse raw data — timeout after 10s per execution.

    Simulates occasional bad data that raises ValueError (~30% chance).
    """
    if random.random() < 0.3:
        raise ValueError("simulated bad data format")
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
