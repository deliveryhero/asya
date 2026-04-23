"""Flow example: real-world tenacity retry patterns with simulated failures.

Uses actual tenacity API — the compiler parses the nested decorator
arguments using where: tree extraction rules:

  @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))

Extracts to manifest:
  spec.resiliency.policies.default:
    maxAttempts: 3
    initialDelay: 1
    maxInterval: 60

Handler functions simulate real failures with random errors so tenacity
retry logic actually fires when running locally.

Compile with:
    asya compile resiliency_tenacity_real.py --output-dir compiled/
"""

import asyncio
import random

from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential

from _asya_utils import actor, flow


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
    Simulates a flaky API that fails ~50% of the time.
    """
    if random.random() < 0.5:
        raise ConnectionError("simulated API timeout")
    p["raw_data"] = "api_response"
    return p


@actor
@retry(stop=stop_after_attempt(5) | stop_after_delay(30))
async def process_response(p: dict) -> dict:
    """Process API response.

    Retries up to 5 times OR 30 seconds total (whichever comes first).
    Simulates occasional parsing failures (~30% chance).
    """
    if random.random() < 0.3:
        raise ValueError("simulated parse error")
    p["processed"] = True
    return p


@actor
def store_results(p: dict) -> dict:
    """Store results — no retry needed."""
    p["status"] = "completed"
    return p
