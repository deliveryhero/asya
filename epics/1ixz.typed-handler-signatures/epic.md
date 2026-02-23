---
title: Typed Handler Signatures
status: slopped
priority: 2 # medium
type: epic
---

Allow typed function signatures where parameters are extracted from payload and return values merged back. Input/output mapping via deployment-time env vars (ASYA_HANDLER_INPUT, ASYA_HANDLER_OUTPUT) with JSONPath-like paths. Supports Pydantic/TypedDict/dataclass. Schema generation for gateway tool exposure. Supersedes the typed-params portion of closed epic 1c84.handler-signature-redesign.
