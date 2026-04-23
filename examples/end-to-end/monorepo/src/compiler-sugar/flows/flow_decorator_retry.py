"""Flow example: @retry decorator with config extraction.

Demonstrates how the compiler extracts resiliency config from decorators:
- @retry(stop=stop_after_attempt(5)) on fetch_data -> maxAttempts: 5
- asyncio.timeout(30) wrapping the scope -> timeout.actor: 30 for scoped actors
- store_results has no retry config (outside timeout scope, no @retry)

The compiler:
1. Detects @retry via the built-in tenacity.retry where: tree rule
2. Navigates into stop_after_attempt(5) to extract max_attempt_number=5
3. Maps to spec.resiliency.policies.default.maxAttempts in the manifest
4. Adds ASYA_IGNORE_DECORATORS=tenacity.retry so runtime strips @retry

Compile with:
    asya compile decorator_retry.py --output-dir compiled/
"""

import asyncio

from tenacity import retry, stop_after_attempt

from _asya_utils import actor, flow


@flow
async def resilient_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = await fetch_data(p)
        p = await transform_data(p)

    p = await store_results(p)
    return p


@actor
@retry(stop=stop_after_attempt(5))
def fetch_data(p: dict) -> dict:
    """Fetch data from external API — retries up to 5 times on failure."""
    p["data"] = "fetched"
    return p


@actor
def transform_data(p: dict) -> dict:
    """Transform fetched data."""
    p["transformed"] = True
    return p


@actor
def store_results(p: dict) -> dict:
    """Store final results."""
    p["stored"] = True
    return p
