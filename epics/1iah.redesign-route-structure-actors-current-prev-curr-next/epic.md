---
title: "Redesign route structure: actors/current to prev/curr/next"
status: slopped
priority: 1 # high
type: epic
---

Migrate the message route schema from `{actors: [...], current: int}` to `{prev: [...], curr: str, next: [...]}`. This is a cross-cutting change that affects sidecar Go structs, runtime Python validation, gateway progress tracking, flow compiler output, and all test fixtures. Must land before 1fbe (HTTP protocol) and 1ixt (msg-metadata-vfs) implementations. Route schema defined in 1ixt/rfc.md section 1.1.
