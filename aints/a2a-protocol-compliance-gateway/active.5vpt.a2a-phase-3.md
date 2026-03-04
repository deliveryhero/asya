---
title: "A2A Phase 2: Tool Registry"
priority: 2 # medium
assignee: Artem Yushkovskiy
---


## Objective

Implement all Phase 3 (tool registry) features for A2A protocol compliance in asya-gateway.
See `rfc.md` and `impl-phases.md`

## Tasks

| # | Ref | Task |
|---|-----|------|
| T9 | `932x` | ListTasks with cursor pagination |
| T10 | `m19w` | CancelTask endpoint |
| T11 | `zr7m` | Blocking mode for SendMessage |
| T12 | `tuw5` | API Key authentication middleware |
| T13 | `8cnd` | Runtime FLY helpers (fly_text, fly_status) |

See each aint for detailed scope and acceptance criteria. See `impl-phases.md` and `rfc.md` in the `a2a-protocol-compliance-gateway` epic for full context.

## Acceptance Criteria

- All 5 tasks implemented and passing tests
- No regressions in existing Phase 1 A2A functionality
- `make test-unit` and `make lint` pass
