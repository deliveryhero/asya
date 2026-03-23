"""Flow example: common retry patterns with simulated failures.

Demonstrates real-world retry configurations for different failure modes:
- API calls: retry with backoff, capped attempts
- Transient errors: fast retry, few attempts
- Storage: patient retry with long timeout
- Validation: no retry, fail fast

Handler functions simulate failures with random errors so tenacity
retry logic fires when running locally.

Compile with:
    asya compile resiliency_retry_patterns.py --output-dir compiled/
"""

import asyncio
import random

from _asya_utils import actor, flow
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential


@flow
async def llm_pipeline(p: dict) -> dict:
    """Multi-step LLM pipeline with different retry strategies per actor."""
    p["status"] = "started"

    # Validate input (no retry — bad input won't improve on retry)
    p = await validate_input(p)

    async with asyncio.timeout(120):
        # Call LLM with moderate retry (API can be flaky)
        p = await call_llm(p)

        # Parse structured output (fast retry — usually transient)
        p = await parse_response(p)

    # Store results (patient retry — storage can be slow)
    p = await store_result(p)
    return p


@actor
def validate_input(p: dict) -> dict:
    """Validate input — no retry, fail fast on bad data."""
    if "prompt" not in p:
        raise ValueError("Missing required field: prompt")
    p["validated"] = True
    return p


@actor
@retry(stop=stop_after_attempt(3) | stop_after_delay(60), wait=wait_exponential(min=1, max=30))
async def call_llm(p: dict) -> dict:
    """Call LLM API — retry up to 3 times or 60s, exponential backoff 1-30s.

    Simulates flaky LLM API (~40% failure rate).
    """
    if random.random() < 0.4:
        raise ConnectionError("simulated LLM API timeout")
    p["response"] = "LLM response"
    return p


@actor
@retry(stop=stop_after_attempt(5))
async def parse_response(p: dict) -> dict:
    """Parse structured output — retry up to 5 times.

    Simulates occasional JSON parsing failures (~25% chance).
    """
    if random.random() < 0.25:
        raise ValueError("simulated malformed JSON from LLM")
    p["parsed"] = True
    return p


@actor
@retry(stop=stop_after_attempt(3) | stop_after_delay(300))
def store_result(p: dict) -> dict:
    """Store results — retry up to 3 times or 5 min total.

    Simulates intermittent storage failures (~20% chance).
    """
    if random.random() < 0.2:
        raise ConnectionError("simulated storage backend unavailable")
    p["stored"] = True
    p["status"] = "completed"
    return p
