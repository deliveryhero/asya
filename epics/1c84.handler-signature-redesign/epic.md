---
title: Handler Signature Redesign
priority: 2 # medium
type: epic
---


Redesign Asya's handler signatures to support typed parameters, output key naming, local variable serialization, and framework-compatible tool definitions. Message metadata access via a virtual filesystem at `/tmp/msg/`.

## Vision

Move beyond the current dict-only handler signatures to support:
1. Typed parameters: `def get_weather(city: str) -> str`
2. Output key naming: where does the result go in the payload?
3. TypedDict/Pydantic payloads: compile-time checking, schema generation
4. Framework decorator detection: @tool from ADK, LangChain, etc.
5. Magic parameter injection: context, stream_writer, tool_context (auto-excluded from schema)
6. Local variable serialization: auto-save/restore across await boundaries
7. **Message metadata as virtual filesystem**: `/tmp/msg/` for route/header access

## Current State
- payload mode: `def handler(p: dict) -> dict` — single dict in, single dict out
- envelope mode: `def handler(e: dict) -> dict` — full envelope access
- No typed params, no output key, no async, no streaming

## Key RFCs
- .aim/aims/1cnt.epic-agent-flow-compi/README.md (CPS transformation, async/await)
- .aim/aims/1dmf.ready-stateful-actors/README.md (transparent filesystem emulation for persistent state — same `open()` interception pattern)
- .aim/aims/1fbe.redesign-protocol-sidecar-runtime/README.md (HTTP over Unix socket protocol — replaces current binary framing)
- docs/rfc/agentic-signatures/survey-agentic-frameworks.md (14-framework survey)

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
- **No asya pip package** — handler signatures must be pure Python
- **No context object injection** — handlers must not have asya-specific parameters
- **File-based metadata access** — follows Linux `/proc` philosophy

---
