---
title: Strip handler decorators by actors
priority: 2 # medium
---

## Resolution

This question has been answered by the compiler rules design brainstorm
(2026-03-08). The answer: **it depends on the rule**.

The compiler uses a declarative `treat-as` system configured in `asya.yaml`:
- `treat-as: config` — strip the decorator, extract args into env vars
- `treat-as: actor` / `treat-as: flow` — keep the decorator, use as classification signal
- No matching rule — keep the decorator at runtime (default)

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for the full
design including:
- Five `treat-as` values: `decompose`, `inline`, `actor`, `flow`, `config`
- Most-specific-pattern-wins rule matching
- Runtime `inspect.signature` for arg extraction from third-party decorators
- Tenacity/stamina/asyncio.timeout extraction examples

## Implementation aints

- [srn2] Decorator detection and rule-based resolution in flow compiler
- [pyn3] Inline comment overrides for compiler rules (`# asya: treat-as-*`)
- [xx8t] Call-site decorator application: `actor(handler)(p)` pattern
- [2t1q] Support context managers (`with`/`async with`) in flow compiler
- [1fmi] Tenacity/stamina retry decorator extraction (backlog)
- [zjt4] Cumulative retry time window — prerequisite for timeout extraction

## Original context

See [1mhs] - it supports custom decorators `@actor`.
See [1fmi] - it wants to support tenacity `@retry`.
