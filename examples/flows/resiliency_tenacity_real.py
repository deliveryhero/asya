"""Flow example: real-world tenacity retry patterns.

Uses actual tenacity API — the compiler parses the nested decorator
arguments using where: tree extraction rules:

  @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))

Extracts to manifest:
  spec.resiliency.policies.default:
    maxAttempts: 3
    initialDelay: 1
    maxInterval: 60

Compile with:
    asya compile resiliency_tenacity_real.py --output-dir compiled/
"""

import asyncio

from _asya_utils import actor, flow
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential


@flow
async def api_pipeline(p: dict) -> dict:
    p["status"] = "started"

    async with asyncio.timeout(120):
        p = await fetch_from_api(p)
        p = await process_response(p)

    p = await store_results(p)
    return p


@actor
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))
async def fetch_from_api(p: dict) -> dict:
    """Fetch from external API.

    Retries up to 3 times with exponential backoff (1s to 60s).
    """
    p["raw_data"] = "api_response"
    return p


@actor
@retry(stop=stop_after_attempt(5) | stop_after_delay(30))
async def process_response(p: dict) -> dict:
    """Process API response.

    Retries up to 5 times OR 30 seconds total (whichever comes first).
    Uses tenacity's BinOp combinator (|) for stop conditions.
    """
    p["processed"] = True
    return p


@actor
def store_results(p: dict) -> dict:
    """Store results — no retry needed."""
    p["status"] = "completed"
    return p
