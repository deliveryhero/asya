---
title: Replace happy-end/error-end with x-sink/x-sump across code, tests, and docs
status: open
priority: 3 # low
type: task
dependencies:
  - misc/1cir
  - misc/1cpu
  - misc/1c9i
  - 1c46/1ct3
---

Remove legacy happy-end and error-end actor names in favor of x-sink and x-sump. This includes:

- Code: Remove actorNameHappyEnd/actorNameErrorEnd constants, update isSystemActor(), remove backward-compat ASYA_ACTOR_HAPPY_END/ASYA_ACTOR_ERROR_END env vars from inject.go, update sidecar routing logic
- Tests: Update all test assertions that reference happy-end/error-end queue names or env vars
- Docs: Update AGENTS.md, architecture docs, message protocol docs, and any examples referencing happy-end/error-end
- Helm charts: Update asya-crew chart and any Crossplane compositions that deploy happy-end/error-end actors
- asya-crew: Rename happy-end/error-end actors to x-sink/x-sump


---
**Close reason**: Renamed all happy-end/error-end references to x-sink/x-sump across 89 files (Go, Python, YAML, JSON, docs). All unit tests and integration tests pass.


---
_Migrated from beads `asya-302b`_
