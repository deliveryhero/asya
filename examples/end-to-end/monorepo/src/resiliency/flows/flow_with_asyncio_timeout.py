"""Flow example: asyncio.timeout context manager (treat-as: config).

The compiler strips the `async with asyncio.timeout(...)` wrapper and records
the timeout value as extracted config with per-scope semantics.  The 30s timeout
applies to the entire scope (ocr_extractor + language_detector combined), not
30s per actor individually.

Compile with:
    asya flow compile with_asyncio_timeout.py --output-dir compiled/
"""

from _asya_utils import flow


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
