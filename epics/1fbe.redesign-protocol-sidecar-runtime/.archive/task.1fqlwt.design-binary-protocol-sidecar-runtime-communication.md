---
title: "Design: Binary protocol for sidecar-runtime communication"
status: wont_do
reason: will better implement http over unix
priority: 2 # medium
type: task
tags:
  - beads:needs-spec
---



Design binary messaging protocol between Go sidecar and Python runtime.

**Goals:**
- Eliminate double deserialization (sidecar + runtime both parsing JSON)
- Zero pip dependencies (no msgpack install required)
- O(1) route extraction (sidecar reads route without touching payload)

**Options evaluated in RFC:**
1. MessagePack/CBOR - requires pip install
2. Protobuf - incompatible with variable/dynamic fields
3. Marshal - Python built-in, 5-10x faster than JSON
4. Custom TLV framing - [Magic][Len][Header][Body]

**Proposed solution:** Marshal-Handshake with TLV framing
- Header: MessagePack (Go can parse for routing)
- Body: Marshal (Python deserializes instantly)
- Handshake for version negotiation

**Risks to address:**
- OOM vulnerability (MAX_HEADER_SIZE limit)
- Debuggability (asya-cli decode tool needed)
- Marshal security (internal traffic only)

RFC: docs/rfc/asya-6j2-binary-protocol.md


---
## Notes

## Related Issues

- asya-866: json.RawMessage optimization (quick win, ~45% improvement, zero risk)
  - Recommended as first step before full binary protocol
- asya-vfx: zlib compression for large envelopes (~60-70% compression, stdlib only)
  - Alternative to binary protocol for size reduction
  - Binary protocol still valuable for future if we need even more efficiency


---
_Migrated from beads `asya-6j2`_
