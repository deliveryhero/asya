"""Flow example: @retry decorator with config extraction.

The compiler detects `@retry(max_attempt_number=3)` on handler functions,
extracts the value to `spec.resiliency.policies.default.maxAttempts: 3`
in the actor manifest, and adds `tenacity.retry` to `ASYA_IGNORE_DECORATORS`
so the runtime strips the decorator at load time.

Compile with:
    asya compile decorator_retry.py --output-dir compiled/
"""

from _asya_utils import actor, flow
from tenacity import retry


@flow
async def resilient_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = fetch_data(p)
        p = transform_data(p)

    p = store_results(p)
    return p


@retry(max_attempt_number=3)
@actor
def fetch_data(p: dict) -> dict:
    """Fetch data from external API with retry on failure."""
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
