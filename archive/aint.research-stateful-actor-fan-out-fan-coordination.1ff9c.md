---
title: "Research: Stateful actor for fan-out/fan-in coordination"
status: merged
priority: 2
parent: 00000
dependencies:
  - 1ffm
tags:
  - beads:needs-spec
---

Design stateful actor for parallel agent coordination (fan-out/fan-in pattern).

Storage options to evaluate:
- PostgreSQL (already used by gateway)
- Redis (fast, but persistence?)
- RocksDB (embedded, on-disk)
- DuckDB (embedded, analytics-friendly)

Considerations:
- Distributed locking complexity
- Latency impact
- Operational simplicity
- Failure recovery
- Session merge semantics

Goal: Minimal external state while supporting true parallel execution.


---
## Notes

## Session Discussion Takeaways (2026-01-28)

- Fan-out/fan-in is the ONLY place requiring external state
- All other session state uses message-truth (no external store)
- This scopes the complexity: only aggregator actor needs DB access
- Distributed locking concerns are isolated to this single pattern
- Options to evaluate:
  - PostgreSQL (already used by gateway - reuse?)
  - Redis (fast, but persistence concerns)
  - RocksDB/DuckDB (embedded, on-disk)
- Key question: how to merge parallel session branches?
- User preference: merge results (not last-write-wins, not isolated branches)


---
_Migrated from beads `asya-zpl`_
