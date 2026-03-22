"""Flow example: @retry decorator with config extraction.

Demonstrates how the compiler extracts resiliency config from decorators:
- @retry(max_attempt_number=5) on fetch_data -> maxAttempts: 5 in manifest
- asyncio.timeout(30) wrapping the scope -> timeout.actor: 30 for both actors
- store_results has no retry config (outside timeout scope, no @retry)

The compiler:
1. Detects @retry via the rule in .asya/config.compiler.rules.yaml
2. Extracts max_attempt_number=5 -> spec.resiliency.policies.default.maxAttempts
3. Adds ASYA_IGNORE_DECORATORS=_asya_utils.retry so runtime strips @retry at load

Compile with:
    asya compile decorator_retry.py --output-dir compiled/
"""

import asyncio

from _asya_utils import actor, flow, retry


@flow
async def resilient_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = await fetch_data(p)
        p = await transform_data(p)

    p = await store_results(p)
    return p


@actor
@retry(max_attempt_number=5)
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
