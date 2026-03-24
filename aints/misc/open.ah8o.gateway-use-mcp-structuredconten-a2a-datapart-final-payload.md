---
title: "Gateway: use MCP structuredContent and A2A DataPart for final payload"
priority: 3 # low
---

## Context

PR #392 (ar84) added final payload as A2A artifacts using TextPart with JSON-serialized content. Spec review identified two alignment gaps:

### MCP: structuredContent (spec 2025-11-25)
MCP tools/call response supports `structuredContent` field — a first-class JSON object alongside human-readable `content`. Per spec: 'a tool that returns structured content SHOULD also return the serialized JSON in a TextContent block.'

Currently the gateway returns tool results without `structuredContent`. The final payload dict should map to `structuredContent` directly, plus a serialized JSON TextContent for backward compat.

### A2A: DataPart (spec v1.0)
A2A Artifact Parts support a `data` type for structured JSON values (object, array, string, number, boolean, null). Current implementation uses TextPart with JSON string — works but forces clients to double-parse. DataPart would be more idiomatic.

### Action items
- [ ] MCP: add `structuredContent` to tool call responses when final payload is available
- [ ] A2A: switch result artifact from TextPart(json_string) to DataPart(structured_value)
- [ ] Check if go-a2a library supports DataPart; if not, extend or upstream

### References
- PR: https://github.com/deliveryhero/asya/pull/392
- A2A spec: https://a2a-protocol.org/latest/definitions/ (Part types: text, raw, url, data)
- MCP spec: https://modelcontextprotocol.io/specification/2025-11-25/server/tools (structuredContent)
