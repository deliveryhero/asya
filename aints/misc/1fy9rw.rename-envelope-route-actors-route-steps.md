---
title: Rename envelope route.actors to route.steps
status: open
priority: 3 # low
type: task
tags:
  - type:feature
---



Rename the envelope schema field `route.actors` to `route.steps` for clarity.

**Rationale**: The term 'steps' is simpler and more intuitive than 'actors' for describing the sequence of processing stages in a route.

**Scope**:
- Update envelope protocol definition in code (Go sidecar, Python runtime)
- Update all documentation references (AGENTS.md, architecture docs)
- Update all tests (unit, component, integration, e2e)
- Update CLI tools and examples

**No backwards compatibility needed** - this is a breaking change that can be applied cleanly.


---
_Migrated from beads `asya-bj4`_
