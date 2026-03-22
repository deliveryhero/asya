"""Flow example: common retry patterns with @retry decorator.

Demonstrates real-world retry configurations for different failure modes:
- API calls: retry with backoff, capped attempts
- Rate limits: patient retry with long max_delay
- Transient errors: fast retry, few attempts
- Critical operations: no retry, fail immediately

Each @retry decorator's args are extracted into the actor manifest's
spec.resiliency.policies.default section by the compiler.

Compile with:
    asya compile resiliency_retry_patterns.py --output-dir compiled/
"""

import asyncio

from _asya_utils import actor, flow, retry


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
@retry(max_attempt_number=3, max_delay=60)
async def call_llm(p: dict) -> dict:
    """Call LLM API — retry up to 3 times, max 60s total.

    Handles transient API errors, rate limits, and network timeouts.
    """
    p["response"] = "LLM response"
    return p


@actor
@retry(max_attempt_number=5)
async def parse_response(p: dict) -> dict:
    """Parse structured output — retry up to 5 times.

    JSON parsing can fail on malformed LLM output; retry triggers
    a fresh LLM call upstream via the sidecar's retry mechanism.
    """
    p["parsed"] = True
    return p


@actor
@retry(max_attempt_number=3, max_delay=300)
def store_result(p: dict) -> dict:
    """Store results — retry up to 3 times, max 5 min total.

    Patient retry for storage backends that may be temporarily unavailable.
    """
    p["stored"] = True
    p["status"] = "completed"
    return p
