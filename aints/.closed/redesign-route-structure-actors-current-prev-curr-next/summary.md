---
title: "Redesign route structure: actors/current to prev/curr/next"
priority: 1 # high
---



Migrate the message route schema from `{actors: [...], current: int}` to `{prev: [...], curr: str, next: [...]}`. Big-bang migration — all components switch at once (no dual-format support). See `rfc.md` for the full migration plan with exact file:line mappings across 40+ locations in 6 components.

Route schema defined in 1ixt/rfc.md section 1.1. Must land before 1ixt (msg-metadata-vfs) implementation. Independent of 1fbe (HTTP protocol) — can be worked in parallel.
