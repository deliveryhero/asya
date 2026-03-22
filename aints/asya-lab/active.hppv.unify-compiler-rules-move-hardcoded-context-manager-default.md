---
title: "Unify compiler rules: move hardcoded context manager and default rules to config"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/asya-lab/hppv.unify-compiler-rules-move-hardcoded-context-manager-default
  - branch:asya-lab/hppv.unify-compiler-rules-move-hardcoded-context-manager-default
  - pr:356
---


## Problem

Two separate rule systems exist in the compiler, one configurable and one hardcoded:

1. **`compiler/rules.py` (RuleEngine)** — configurable via `.asya/config.compiler.rules.yaml`.
   Handles call-site classification with `where:` tree extraction and 4-tier wildcard
   matching (`"."`, `"*"`, `"prefix.*"`, exact). Overly complex.

2. **`flow/rules.py` (CompilerRules)** — hardcoded. Handles context manager classification
   only. Two built-in rules (`asyncio.timeout` -> config, `contextlib.suppress` -> inline)
   are baked into `_DEFAULT_RULES` dict. Cannot be extended without modifying source code.

### What's hardcoded today

| Hardcoded item | Location | Purpose |
|---|---|---|
| `asyncio.timeout` -> config | `flow/rules.py:28-39` | Context manager: extract `delay` param |
| `contextlib.suppress` -> inline | `flow/rules.py:28-39` | Context manager: wrap router body |
| `"."` -> UNFOLD | `compiler/rules.py:142-145` | Same-package symbol default |
| `"*"` -> INLINE | `compiler/rules.py:142-145` | Global fallback |

## Design

### Simplified classification (no wildcards)

Remove the entire tier/wildcard matching system. Classification is now:

1. **Explicit annotation** (highest priority):
   - `@actor`, `@flow`, `@inline`, `@unfold` decorators on function definitions
   - `# asya: actor` inline comment directives on call sites
   - `actor(fn)(p)` call-site wrappers
2. **Implicit defaults** (no annotation):
   - Same-package function → **inline** (code runs in router)
   - Third-party function → **mutation** (e.g., `uuid4()`, `len()`)
   - Never implicitly treated as actor — actors MUST be explicitly annotated

No `"."`, `"*"`, `./*`, or prefix wildcards. Exact-match rules only in config.

**Future extension** (out of scope): `external_package.module.actors.*: treat-as: actor`
wildcard syntax for bulk classification.

### Context manager rules from config

Move hardcoded context manager rules to `config.compiler.rules.yaml` with
`scope: context-manager`:

```yaml
# .asya/config.compiler.rules.yaml

# Context manager rules
- match: "asyncio.timeout"
  scope: context-manager
  treat-as: config
  extract:
    delay: spec.resiliency.timeout.actor

- match: "contextlib.suppress"
  scope: context-manager
  treat-as: inline
  imports: ["import contextlib"]

# Explicit symbol overrides (exact match only)
- match: "tenacity.retry"
  treat-as: config
  where:
    - param: stop
      where:
        - param: {arg: 0, kwarg: "max_attempt_number"}
          assign-to: spec.resiliency.policies.default.maxAttempts
```

### Default rules as shipped YAML

Ship `src/asya-lab/asya_lab/defaults/compiler.rules.yaml` with the default
context manager rules. User config extends (not replaces) defaults.

## Implementation plan

1. **Simplify `compiler/rules.py`**: remove tier system, keep only exact-match
   classification. Remove `"."` and `"*"` default rules.
2. **Update `flow/parser.py` defaults**: same-package → inline, external → mutation
3. **Move context manager rules to config**: `flow/rules.py` loads from config
   file instead of `_DEFAULT_RULES`
4. **Ship default rules file**: `defaults/compiler.rules.yaml` with
   `asyncio.timeout` and `contextlib.suppress`
5. **Update tests**: adjust for new classification defaults
6. **Update flow-dsl.md**: document simplified rule system

## Acceptance criteria

- [ ] Context manager rules loaded from config, not hardcoded
- [ ] Users can add custom context manager rules via config
- [ ] No wildcard matching — exact match only
- [ ] Same-package functions default to inline, external to mutation
- [ ] Actors/flows require explicit annotation
- [ ] Default rules shipped as YAML file
- [ ] Existing flows compile correctly (backward compat)
- [ ] Unit tests updated

## References

- `src/asya-lab/asya_lab/flow/rules.py` — hardcoded context manager rules
- `src/asya-lab/asya_lab/compiler/rules.py` — classification rules engine
- `.aint/aints/asya-lab/research-compiler-knowledge-base.md` — rules engine design
