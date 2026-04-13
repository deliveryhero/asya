---
title: "ADR: Route format change scoped out of 1fbe"
date: 2026-02-23
status: accepted
---

## Decision

The route format migration (`{actors, current}` → `{prev, curr, next}`) is **not part of this epic**. The HTTP protocol migration uses the existing `{actors, current}` route format.

## Context

The 1fbe epic.md examples use `{prev, curr, next}` route format, which is defined in the 1ixt (msg-metadata-vfs) RFC. However, the route format change is a cross-cutting migration that affects every component (sidecar, runtime, gateway, flow compiler, all tests).

Bundling it with the HTTP protocol migration doubles the blast radius and makes it impossible to validate the HTTP change in isolation.

## Consequence

- All 1fbe request/response examples should be read with `{actors, current}` format
- Route format migration is tracked in epic 1iah
- 1fbe tasks should NOT implement `{prev, curr, next}` — use existing structs
- After both 1fbe and 1iah land, the wire format will be HTTP + `{prev, curr, next}`
