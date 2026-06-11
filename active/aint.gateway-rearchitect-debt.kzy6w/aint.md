---
title: Gateway rearchitect debt
status: open
priority: 3 # low
tags: [gateway-rearchitect]
---

Debt items from gateway rearchitecture PRs 1-2.

- PR1 (#442): PG state-proxy connector (pg-kv) + asya-mesh-api core
- PR2 (#444): MCP Streamable HTTP + A2A JSON-RPC adapters

Source: code review, RFC conformance review (RFC at `rfc.md` in parent aint),
and static analysis findings deferred to avoid scope creep in the initial PRs.

## Sub-aints

| ID | P | Title | Category |
|----|---|-------|----------|
| a5qqw | P2 | A2A tasks/subscribe for in-flight tasks | functionality gap |
| dpg3j | P3 | Wire A2A StoreAdapter.List to mesh-api | functionality gap |
| fuj1p | P3 | A2A history hydration from state-proxy-s3 | RFC SHOULD |
| 63od4 | P3 | Rename mcpadapter→mcp, a2aadapter→a2a | post-migration cleanup |
| 5pgt0 | P3 | Extract shared cmdutil from adapter mains | code duplication |
| bd256 | P2 | Fix G120 gosec: OAuth MaxBytesReader | security |
| av2bh | P3 | Fix revive lint in legacy packages | code quality |
| 2swbh | P3 | Consider sseclient to pkg/ | structure |
| tr8vc | P2 | A2A task id ≠ mesh envelope id (breaks --show-traces, tasks/get) | observability/bug |
