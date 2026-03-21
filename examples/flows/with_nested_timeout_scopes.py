"""Flow example: nested asyncio.timeout scopes with per-scope semantics.

Demonstrates that each context manager scope tracks its own actors:
- Outer scope (60s): covers all 3 actors (fetch, parse, validate)
- Inner scope (10s): covers only parse + validate

The compiler extracts both timeouts with their respective scope_actors,
enabling the runtime to enforce scope-level deadlines rather than
per-actor timeouts.

Compile with:
    asya flow compile with_nested_timeout_scopes.py --output-dir compiled/
"""

from _asya_utils import flow


@flow
async def ingestion_pipeline(p: dict) -> dict:
    async with asyncio.timeout(60):
        p = data_fetcher(p)

        async with asyncio.timeout(10):
            p = data_parser(p)
            p = data_validator(p)

    p = data_writer(p)
    return p
