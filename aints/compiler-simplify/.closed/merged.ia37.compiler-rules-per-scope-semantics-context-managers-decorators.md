---
title: "Compiler rules: per-scope semantics for context managers, decorators, and single calls"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/compiler-simplify/ia37.compiler-rules-per-scope-semantics-context-managers-decorators
  - branch:compiler-simplify/ia37.compiler-rules-per-scope-semantics-context-managers-decorators
  - pr:342
---






## Problem

The current context manager implementation ([2t1q]) applies extracted config
**per-actor**: each actor inside a `with` block gets the config independently.
For example, `asyncio.timeout(30)` wrapping 3 actors gives each actor a 30s
timeout individually.

The correct semantics is **per-scope**: the extracted config applies to the
scope as a whole. `asyncio.timeout(30)` wrapping 3 actors means the entire
pipeline segment must complete in 30s total.

## Decision

All compiler rules should be applied **per scope**. Three scope types:

1. **Context manager** — `async with asyncio.timeout(30):` → config applies to
   the entire body (pipeline-level deadline, not per-actor timeout)
2. **Decorated function** — `@retry(3) def handler(p):` → config applies to
   the handler itself (natural, already correct)
3. **Single function call** — `p = actor(p)` → config applies to that one call
   (trivially per-scope = per-actor)

## Impact

### Context managers (the change)

Currently `asyncio.timeout(30)` extracts to `ASYA_RESILIENCY_ACTOR_TIMEOUT`
(see details in 7179: .aint/aints/resiliency/.closed/merged.7179.policy-based-error-handling-policies-retryrules.md)
on each actor within the scope. With per-scope semantics:

- The timeout becomes a **scope-level deadline**, not a per-actor env var
- Implementation options:
  - Router at scope entry sets `deadline_at` header in the envelope
  - Gateway tracks pipeline-level SLA via `deadline_at`
  - Or: the config is applied to the first actor in the scope as a cumulative
    deadline rather than an individual timeout

### Decorators and single calls (no change)

Per-scope for decorators and single calls already matches current behavior:
- `@retry(3)` on a handler → retry that handler (scope = the function)
- Single `actor(p)` call → config applies to that call (scope = one actor)

## References

- `.aint/aints/asya-lab/research-compiler-knowledge-base.md` — documents the
  per-actor design and this open question (§ open questions)
- `.aint/aints/asya-lab/rfc.md` §9.1 — compiler rules summary
- Aint [2t1q] — context manager implementation (per-actor, needs updating
  to per-scope once this aint is implemented)
- Aint [zjt4] — `deadline_at` SLA enforcement (prerequisite for scope-level
  timeout implementation)
