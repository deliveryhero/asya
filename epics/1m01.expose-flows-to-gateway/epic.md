---
title: "Expose flows and actors to gateway via DB-backed registry"
status: ideated
priority: 2
type: epic
---

Replace YAML-based static tool config with a PostgreSQL `tools` table and
REST API (`POST /tools/expose`). Flows and standalone actors are registered
dynamically, exposed as MCP tools and A2A skills without gateway restart.

See `rfc.md` in this directory for the full design.

Key decisions:
- Flow metadata (entrypoint, input schema, description) is business logic,
  not K8s/infra — stored in gateway DB, not ConfigMaps or CRDs
- Single entrypoint actor per tool (CPS model — routers handle continuation)
- Dual-channel A2A Messages: FLY for streaming, meshage `history` for canonical turns
- A2A Context = meshage identity; multi-turn = pause-resume cycles
- No payload data in PostgreSQL — only tool/skill metadata and task status

Supersedes epic 1iqd (design workflow for asya flows).
Related: 1c0d (A2A protocol), 1ixy (pause-resume), 1l01 (ABI), 1mx1 (meshage rename).
