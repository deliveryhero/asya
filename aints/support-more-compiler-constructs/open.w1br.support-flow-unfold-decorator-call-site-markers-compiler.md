---
title: "Support @flow and @unfold decorator/call-site markers in compiler"
priority: 2 # medium
---

Add `@flow`, `@unfold` as decorator markers and `flow(func)(p)`, `unfold(func)(p)` as call-site markers.

## Context

The compiler rules system classifies every symbol into one of five actions: `actor`, `flow`, `unfold`, `inline`, `config`. Existing aints cover:
- [srn2] — `@actor` decorator detection and rule-based resolution
- [xx8t] — `actor(handler)(p)` and `inline(uuid4)(p)` call-site patterns
- [pyn3] — `# asya: inline` / `# asya: actor` / etc. inline comment overrides

Missing: `@flow` and `@unfold` as decorator markers, and their call-site equivalents.

## Full marker matrix

| Marker | Decorator | Call-site | Inline comment | Covered by |
|--------|-----------|-----------|----------------|------------|
| `actor` | `@actor` | `actor(func)(p)` | `# asya: actor` | [srn2], [xx8t], [pyn3] |
| `inline` | `@inline` | `inline(func)(p)` | `# asya: inline` | [srn2], [xx8t], [pyn3] |
| `flow` | `@flow` | `flow(func)(p)` | `# asya: flow` | **this aint** + [pyn3] |
| `unfold` | `@unfold` | `unfold(func)(p)` | `# asya: unfold` | **this aint** + [pyn3] |

## Design

The `@flow` and `@unfold` markers use the same decorator detection mechanism as `@actor` ([srn2]) and the same call-site pattern as `actor(handler)(p)` ([xx8t]). The compiler already has the infrastructure — this aint adds the two missing marker names to the recognized set.

### `@flow` semantics
- Sub-flow: compile the function body recursively as a separate flow
- Creates a boundary (separate deployment of the sub-flow's routers)

### `@unfold` semantics
- Expand the function body into the current flow's routers
- No boundary — the function's operations merge into the parent flow
- This is already the default for same-package functions (`"."` rule), so `@unfold` is mainly useful for overriding the `"*"` rule on external functions

## Testing
- Unit: `@flow` decorator → FlowCall (recursive compilation)
- Unit: `@unfold` decorator → unfold (body expansion)
- Unit: `flow(sub_pipeline)(p)` call-site → FlowCall
- Unit: `unfold(helper)(p)` call-site → unfold
- Unit: `@flow` on external function → overrides `"*"` inline default
- Unit: `@unfold` on external function → overrides `"*"` inline default
