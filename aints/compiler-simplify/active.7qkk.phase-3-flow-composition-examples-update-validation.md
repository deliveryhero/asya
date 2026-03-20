---
title: "Phase 3: Flow composition, examples update, and validation"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/compiler-simplify/7qkk.phase-3-flow-composition-examples-update-validation
  - branch:compiler-simplify/7qkk.phase-3-flow-composition-examples-update-validation
  - pr:340
dependencies:
  - gml9
---



## Overview

Add flow composition (inline expansion), update all existing flow examples
to verify parity with the old compiler, and add comprehensive test coverage.
After this phase: compiler simplification is complete and validated.

## What to implement

### 1. Flow composition (compile-time inlining)

When a `@flow` calls another `@flow`, compiler inlines the inner flow body:

```python
@flow
async def outer(p):
    p = await step_a(p)
    p = await inner_flow(p)   # another @flow
    p = await step_b(p)
    return p
```

Behavior:
- Expand inner_flow's body inline at compile time
- All actors get `asya.sh/flow=outer` (outermost flow label)
- Inner flow actors appear in a `group` in graph.json for visual clustering
- No additional K8s labels for inner flows
- Multiple nesting levels → nested groups
- Each reference to same inner flow creates NEW actor instances (not shared)
- No runtime nesting — purely compile-time expansion

### 2. Update existing flow examples

Re-compile all flows in `examples/flows/` with the new compiler and verify
graph outputs match expected topology:

- `examples/flows/compiled/if_else_simple/`
- `examples/flows/compiled/if_nested/`
- `examples/flows/compiled/fanout_comprehension/`
- `examples/flows/compiled/try_except_simple/`
- All other compiled/ directories

For each:
1. make sure they're not ignored in `.pre-commit-hooks/compile-flows.sh`, run pre-commit to compile them
2. Verify routers.py produces equivalent runtime behavior
3. Verify graph.json/DOT/Mermaid show correct topology
4. Commit updated compiled/ outputs

### 3. Edge case validation

Test and verify:
- **Single-actor flow**: `role: entry`, single entry router generated
- **No-op flow**: `role: entry`, single entry router generated
- **Multiple exitpoints**: branching flow with multiple returns
- **Nested if/while**: chain of routers (one decision per router, P13)
- **FanOut patterns**: comprehension, literal, gather
- **External package handler**: opaque node when source unavailable
- **Handler with stripped decorators**: ASYA_IGNORE_DECORATORS in manifest
- **Mixed flow + actor routing (scenario E)**: yield analysis override edges
- **yield "SET", ".route.next", []**: abort to x-sink (not break)

### 4. Comprehensive test suite

Unit tests:
- Parser: all 5 operation types from various flow patterns
- Parser: unmatched constructs → compile errors
- Codegen: nested if/while → router chains (P13 invariant)
- Analyzer: _extract_yield_edges for each ABI pattern
- Analyzer: three handler categories (generated, user, external)
- Analyzer: merge algorithm (chains + overrides + error edges)
- Graphgen: DOT/Mermaid/JSON output correctness

Integration tests:
- End-to-end: flow.py → compile() → FlowInfo with correct graph
- Parity: old compiled examples match new compiler output (topology, not byte-exact)

### 5. Superseded aints

After this phase completes, close these aints as superseded:
- `[20c9]` Don't generate empty start/end routers → subsumed by smart entrypoint detection
- `[w1br]` Support @flow and @unfold decorator/call-site markers → subsumed by flow composition
- `[w76v]` Sidecar retryableErrors whitelist → subsumed by aint 7179 policies

## Key files

- `src/asya-lab/asya_lab/flow/parser.py` (add inline expansion logic)
- `src/asya-lab/asya_lab/flow/compiler.py` (handle @flow-calls-@flow)
- `examples/flows/` (all flow sources)
- `examples/flows/compiled/` (all compiled outputs — regenerate)
- `src/asya-lab/tests/` (new test files)

## References

- RFC: `.aint/aints/compiler-simplify/rfc.md` (sections: Flow composition, Edge Cases, User Workflow Catalog, What disappears, Relationship to existing work)
- Design decisions: `.aint/aints/compiler-simplify/design-decisions.md` (W6, W7)
- Existing compiled examples for parity: `examples/flows/compiled/if_nested/flow.mmd`
