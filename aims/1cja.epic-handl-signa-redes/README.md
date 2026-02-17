---
title: "Epic: Handler Signature Redesign"
status: open
priority: 2 # medium
type: epic
---

Redesign Asya's handler signatures to support typed parameters, output key naming, local variable serialization, and framework-compatible tool definitions.

## Vision
Move beyond the current dict-only handler signatures to support:
1. Typed parameters: `def get_weather(city: str) -> str`
2. Output key naming: where does the result go in the payload?
3. TypedDict/Pydantic payloads: compile-time checking, schema generation
4. Framework decorator detection: @tool from ADK, LangChain, etc.
5. Magic parameter injection: context, stream_writer, tool_context (auto-excluded from schema)
6. Local variable serialization: auto-save/restore across await boundaries

## Current State
- payload mode: `def handler(p: dict) -> dict` — single dict in, single dict out
- envelope mode: `def handler(e: dict) -> dict` — full envelope access
- No typed params, no output key, no async, no streaming

## Key RFCs
- docs/rfc/agentic-compiler/agentic-compiler-rfc.md (CPS transformation, async/await)
- docs/rfc/agentic-signatures/asya-handler-signatures.md (typed signatures research)
- docs/rfc/agentic-signatures/asya-handler-syntax-comparisons.md (14-framework survey)

## Champion Framework: Google ADK
ADK is the closest architectural match for Asya. Key patterns to adopt:
- output_key (enrichment into shared state)
- Plain functions as tools (no decorator required)
- tool_context magic parameter injection
- Event-based async generators

## Design Decisions (from RFC discussions)
- Last yield = control event (Option B), emit callback rejected
- Enrichment is custom reducer (payload in -> payload out), not append-only
- Free variables across await boundaries: initially error, later auto-serialize
- LangGraph reducer pattern (Annotated[list, add]) — NOT adopted (confusing, scales poorly)


---
## Notes

[Error Handling RFC context] The handler signature redesign must support optional headers access for retry_after override. Example use case: when an LLM API returns 429 with Retry-After header, the handler should be able to signal a custom retry delay:

```python
async def handler(payload: dict, headers: dict):
    try:
        result = await llm.call(payload)
        return {"result": result}
    except RateLimitError as e:
        headers["_error"] = {"retry_after_ms": e.retry_after * 1000}
        raise  # re-raise so runtime treats it as error
```

This connects to the error handling RFC (asya-y4kr): the _error crew actor checks for retry_after_ms in headers and uses max(computed_backoff, retry_after_ms) as the delay. Requires the new handler signature where headers are optionally injectable.


---
_Migrated from beads `asya-0gsw`_
