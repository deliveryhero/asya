---
title: Message Serialization Optimization
priority: 3 # low
---

## Context

This epic was originally a large RFC exploring binary protocols (TLV + Python
`marshal`, MessagePack, custom framing) for the sidecar↔runtime transport, to
eliminate "double deserialization" and stay zero-pip.

The premise changed in two ways:

1. **Sidecar↔runtime transport is now HTTP over Unix Domain Socket** (`POST
   /invoke`, `Content-Type: application/json`). HTTP framing handles
   length-prefixing natively, making TLV/custom-framing designs moot.

2. **The "double deserialization" problem was solved by `json.RawMessage`.**
   The `Envelope.Payload` field is typed as `json.RawMessage`, so when the
   sidecar deserializes a queue message it only parses the small structural
   fields (id, route, headers, status) — the payload bytes are kept verbatim
   and forwarded to the runtime as-is via `json.Marshal(msg)`. The runtime
   performs the first and only full parse of the payload content. No binary
   format needed.

The full RFC is preserved in git history.

## Surviving Conclusion

The RFC's final verdict (Section 15): **JSON + zlib** gives ~60-70% compression
with zero pip dependencies and zero custom protocol maintenance — the best
cost/benefit ratio for Asya's constraints.

This applies to the **queue layer** (sidecar → queue → sidecar direction), not
the sidecar↔runtime HTTP layer. Compression is transparent to handlers —
the runtime always receives uncompressed JSON.

## Open Work

- `1f9a` — Add optional zlib compression for large queue envelopes
  (`ASYA_COMPRESSION=zlib|none`, threshold-based, magic byte `0x78` prefix)

## Rejected Approaches

- **TLV + Marshal**: Requires custom Go encoder for Python's `marshal` format;
  moot now that sidecar↔runtime is HTTP.
- **MessagePack**: Requires `pip install` — violates zero-pip constraint.
- **Custom binary framing**: Observability cost (SREs can't inspect queue
  messages), OOM risk from untrusted length headers, fragile slice arithmetic.
- **zstd / MessagePack + zlib**: All require pip.
