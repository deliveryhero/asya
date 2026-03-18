"""Flow example: asyncio.timeout context manager (treat-as: config).

The compiler strips the `async with asyncio.timeout(...)` wrapper and records
the timeout value as `ASYA_RESILIENCY_ACTOR_TIMEOUT` metadata.  The generated
router code contains no `async with` block -- actors in the scope run under the
timeout configured at the actor level, not inside a Python context manager.

Compile with:
    asya flow compile with_asyncio_timeout.py --output-dir compiled/
"""
from asya_lab.flow import flow


@flow


async def document_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = ocr_extractor(p)
        p = language_detector(p)

    if p.get("language") != "en":
        p = translator(p)

    p = sentiment_analyzer(p)
    p["status"] = "done"
    return p
