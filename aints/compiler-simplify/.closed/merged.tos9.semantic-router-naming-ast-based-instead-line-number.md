---
title: "Semantic router naming: AST-based instead of line-number-based"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/compiler-simplify/tos9.semantic-router-naming-ast-based-instead-line-number
  - branch:compiler-simplify/tos9.semantic-router-naming-ast-based-instead-line-number
  - pr:366
---





## Problem

Generated router names are tied to source line numbers:

```
router_data_pipeline_line_28_except_2
router_data_pipeline_line_15_if_1
router_data_pipeline_line_20_while_3
```

These are fragile — adding a comment, import, or blank line shifts every name.
This causes:
- Manifest churn in git diffs (renamed YAML files on every reformat)
- Broken test assertions that match on router names
- Hard-to-read graph.json and DOT output

## Proposed design

Replace line numbers with semantic names derived from AST content:

### Naming rules by router type

| Router type | Current | Proposed | Disambiguation |
|---|---|---|---|
| **Start** | `start_{flow}` | `start_{flow}` | Unchanged (one per flow) |
| **Conditional** | `router_{flow}_line_{N}_if_{id}` | `router_{flow}_if_{condition_slug}` | Counter if duplicate conditions |
| **Except** | `router_{flow}_line_{N}_except_{id}` | `router_{flow}_except_{error_types_slug}` | Counter if duplicate error sets |
| **Seq (mutations)** | `router_{flow}_line_{N}_seq_{id}` | `router_{flow}_seq_{first_mutation_slug}` | Counter for ambiguity |
| **While** | `router_{flow}_line_{N}_while_{id}` | `router_{flow}_while_{condition_slug}` | Counter if duplicate loops |
| **Fan-out** | `fanout_{flow}_line_{N}` | `fanout_{flow}_{target_key_slug}` | Counter if duplicate fan-outs |
| **Fan-in** | `fanin_{flow}_line_{N}` | `fanin_{flow}_{target_key_slug}` | Matches fan-out |

Where `flow` is flow name (not flow function name!).

### Slug generation

Derive a short, readable slug from the AST content:

| AST content | Slug |
|---|---|
| `p["status"] == "done"` | `status_eq_done` |
| `p.get("language") != "en"` | `language_ne_en` |
| `True` (while True) | `loop` |
| `p["attempt"] < 3` | `attempt_lt_3` |
| `ValueError` | `valueerror` |
| `(ConnectionError, TimeoutError)` | `connectionerror_timeouterror` |
| `p["status"] = "processing"` | `set_status` |

Rules:
- All slugs are **lowercased** (K8s resource names must be lowercase)
- Extract key name from subscripts: `p["key"]` -> `key`, `p.get("key")` -> `key`
- Extract operator: `==` -> `eq`, `!=` -> `ne`, `<` -> `lt`, `>` -> `gt`, `<=` -> `le`, `>=` -> `ge`
- Extract value: string/number constants, keep short
- Truncate slugs at 40 chars, append hash suffix if truncated
- Replace non-alphanumeric with `_`

### Policy naming

Retry policies from try/except also get semantic names:

| Current | Proposed |
|---|---|
| `try_except_line_28_0` | `except_valueerror` |
| `try_except_line_28_1` | `except_connectionerror` |
| `try_except_line_28_bare` | `except_all` |

### Corner cases

**Duplicate conditions** — two `if p["status"] == "done"` in the same flow:
```
router_{flow}_if_status_eq_done
router_{flow}_if_status_eq_done_2
```
Counter appended only when needed (first occurrence has no suffix).

**Nested conditionals** — `if` inside `if`:
```
router_{flow}_if_category_eq_urgent      # outer
router_{flow}_if_priority_gt_5           # inner (own condition)
```
Each conditional gets its own slug from its own condition. No nesting in the name.

**elif chains** — `if/elif/else`:
```
router_{flow}_if_type_eq_express         # first condition
router_{flow}_if_type_eq_bulk            # elif condition
```
Each branch point is a separate router with its own condition slug.

**while with break/continue**:
```
router_{flow}_while_attempt_lt_3         # loop router
```
`break` and `continue` don't generate routers — they modify `route.next` inline.

**Bare except** (no error type):
```
router_{flow}_except_all
```

**Tuple exception types** — `except (ValueError, TypeError)`:
```
router_{flow}_except_valueerror_typeerror
```

**FQN exception types** — `except openai.RateLimitError`:
```
router_{flow}_except_ratelimiterror
```
Use the short name (last component) to keep it readable.

**Seq routers** (mutation batches) — named after the first mutation:
```
router_{flow}_seq_set_status             # p["status"] = "processing"
router_{flow}_seq_set_count              # p["count"] += 1
```

**Fan-out/fan-in** — named after the target key:
```
fanout_{flow}_results                    # p["results"] = [...]
fanin_{flow}_results                     # aggregator for above
```

**Flow composition groups** — sub-flow routers keep the sub-flow name:
```
router_{flow}_if_category_eq_urgent      # in main flow
router_{subflow}_if_valid                # in expanded sub-flow
```

### K8s manifest naming

Router names map to K8s resource names via `_` -> `-`:
```
asya-router-data-pipeline-if-status-eq-done.yaml
asya-router-data-pipeline-except-valueerror.yaml
```

K8s name limit is 253 chars — well within bounds for semantic names.

## Implementation

The change is in `codegen.py` where router names are generated. Each
`_RouterFunc` gets its name from the AST content instead of line number.
The `_router_counter` disambiguates duplicates.

### Files to change

- `src/asya-lab/asya_lab/flow/codegen.py` — router name generation
- `src/asya-lab/tests/` — update assertions on router names
- `examples/flows/compiled/` — all recompiled (one-time churn)
- `docs/reference/specs/flow-dsl.md` — update router naming table

## Acceptance criteria

- [ ] Router names derived from AST content, not line numbers
- [ ] Adding/removing blank lines doesn't change router names
- [ ] Duplicate conditions disambiguated with counter suffix
- [ ] Policy names semantic (`except_valueerror` not `try_except_line_28_0`)
- [ ] All example flows recompile with stable names
- [ ] graph.json, DOT, Mermaid use semantic names
- [ ] K8s manifest filenames use semantic names
