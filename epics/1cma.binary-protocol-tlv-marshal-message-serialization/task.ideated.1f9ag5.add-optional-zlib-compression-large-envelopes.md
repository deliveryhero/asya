---
title: Add optional zlib compression for large envelopes
priority: 3 # low
type: task
tags:
  - type:feature
---




Add optional zlib compression layer for envelope payloads to maximize effective queue capacity.

**Use case:** Agentic workloads with large session state hitting SQS 256KB limits.

**Benefits:**
- ~60-70% compression ratio on JSON
- Python stdlib: `zlib` built-in
- Go stdlib: `compress/zlib` native
- Zero pip dependencies
- Zero custom protocol maintenance

**Implementation:**
1. Add compression flag to envelope headers: `{"compression": "zlib"}`
2. Sidecar compresses payload before sending to queue
3. Sidecar decompresses after receiving from queue
4. Runtime sees uncompressed JSON (transparent to handlers)

**Wire format:**
```
[Magic byte 0x78 (zlib)][Compressed JSON payload]
```

**Configuration:**
- `ASYA_COMPRESSION=zlib|none` (default: none)
- `ASYA_COMPRESSION_THRESHOLD=1024` (only compress if payload > N bytes)

**Related:** asya-6j2 (binary protocol RFC), asya-866 (RawMessage optimization)


---
_Migrated from beads `asya-vfx`_
