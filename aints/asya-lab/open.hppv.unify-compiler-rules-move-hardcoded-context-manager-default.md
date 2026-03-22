---
title: "Unify compiler rules: move hardcoded context manager and default rules to config"
priority: 2 # medium
---

## Problem

Two separate rule systems exist in the compiler, one configurable and one hardcoded:

1. **`compiler/rules.py` (RuleEngine)** — configurable via `.asya/config.compiler.rules.yaml`.
   Handles call-site classification with `where:` tree extraction. User rules prepend to
   defaults and win on specificity. Works well.

2. **`flow/rules.py` (CompilerRules)** — hardcoded. Handles context manager classification
   only. Two built-in rules (`asyncio.timeout` -> config, `contextlib.suppress` -> inline)
   are baked into `_DEFAULT_RULES` dict. Cannot be extended without modifying source code.

Additionally, the default classification rules (`"."` -> UNFOLD, `"*"` -> INLINE) are
hardcoded in `compiler/rules.py:142-145` and appended to user rules. While these sensible
defaults should exist, they should be overridable via config without code changes.

### What's hardcoded today

| Hardcoded item | Location | Purpose |
|---|---|---|
| `asyncio.timeout` -> config | `flow/rules.py:28-39` | Context manager: extract `delay` param |
| `contextlib.suppress` -> inline | `flow/rules.py:28-39` | Context manager: wrap router body |
| `"."` -> UNFOLD | `compiler/rules.py:142-145` | Same-package symbol default |
| `"*"` -> INLINE | `compiler/rules.py:142-145` | Global fallback |

## Proposed design

### 1. Unify context manager rules into `config.compiler.rules.yaml`

Context manager rules should use the same config file as classification rules. Add a
`scope: context-manager` field to distinguish them from call-site rules:

```yaml
# .asya/config.compiler.rules.yaml

# Context manager rules (scope: context-manager)
- match: "asyncio.timeout"
  scope: context-manager
  treat-as: config
  where:
    - param: delay
      assign-to: spec.resiliency.timeout.actor

- match: "contextlib.suppress"
  scope: context-manager
  treat-as: inline
  imports: ["import contextlib"]

# Call-site classification rules (scope: call, default)
- match: "tenacity.retry"
  treat-as: config
  where:
    - param: stop
      where:
        - param: {arg: 0, kwarg: "max_attempt_number"}
          assign-to: spec.resiliency.policies.default.maxAttempts

# Default classification (lowest priority)
- match: "./*"
  treat-as: unfold

- match: "*"
  treat-as: inline
```

### 2. Wildcard syntax clarification

Current `"."` syntax for "same-package symbols" is non-obvious. Proposed change:

| Current | Proposed | Meaning |
|---|---|---|
| `"."` | `./*` | Current package, any symbol (filesystem analogy) |
| `"*"` | `*` | Global wildcard (unchanged) |
| `"tenacity.*"` | `tenacity.*` | Prefix wildcard (unchanged) |
| `"tenacity.retry"` | `tenacity.retry` | Exact match (unchanged) |

`./*` reads naturally: "dot-slash = current package, star = any name within it".
Matches filesystem convention (`./file` = current directory).

**Migration**: support both `"."` and `./*` during transition, deprecate `"."`.

### 3. Default rules as a shipped config file

Ship a `defaults.compiler.rules.yaml` alongside the code that provides sensible defaults.
User config prepends (higher priority). This makes defaults visible and editable without
touching source code.

## Implementation plan

1. **Extend rule config schema**: add `scope: context-manager | call` field (default: `call`)
2. **Load context manager rules from config**: `flow/rules.py` reads from config instead of
   hardcoding `_DEFAULT_RULES`
3. **Wildcard syntax**: add `./*` as alias for `"."`, deprecate bare `"."`
4. **Ship default rules file**: create `src/asya-lab/asya_lab/defaults/compiler.rules.yaml`
   with the current hardcoded defaults
5. **Update flow-dsl.md**: document unified rule syntax

## Acceptance criteria

- [ ] Context manager rules (`asyncio.timeout`, `contextlib.suppress`) loaded from config
- [ ] Users can add custom context manager rules without code changes
- [ ] `./*` wildcard works as alias for `"."`
- [ ] Default rules shipped as a YAML file, not hardcoded
- [ ] Existing `.asya/config.compiler.rules.yaml` files continue to work (backward compat)
- [ ] Unit tests cover config-loaded context manager rules

## References

- `src/asya-lab/asya_lab/flow/rules.py` — hardcoded context manager rules
- `src/asya-lab/asya_lab/compiler/rules.py` — configurable classification rules
- `.aint/aints/asya-lab/research-compiler-knowledge-base.md` — rules engine design
- `.aint/aints/compiler-simplify/rfc.md` — RFC section 9.1 (compiler rules summary)
