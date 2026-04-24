---
title: Strip handler decorators by actors
status: merged
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:280
  - pr:329
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
- Five `treat-as` values: `unfold`, `inline`, `actor`, `flow`, `config`
- Most-specific-pattern-wins rule matching
- Runtime `inspect.signature` for arg extraction from third-party decorators
- Tenacity/stamina/asyncio.timeout extraction examples

## Implementation aints

- [srn2] Decorator detection and rule-based resolution in flow compiler
- [pyn3] Inline comment overrides for compiler rules (`# asya: <action>`)
- [xx8t] Call-site decorator application: `actor(handler)(p)` pattern
- [2t1q] Support context managers (`with`/`async with`) in flow compiler
- [1fmi] Tenacity/stamina retry decorator extraction (backlog)
- [zjt4] Cumulative retry time window — prerequisite for timeout extraction

## Design change (2026-03-08)

Inline comment syntax simplified: `# asya: actor` / `# asya: inline` (no `treat-as-` prefix).
Regex pattern: `#\s*asya:\s*(\w+)(?:\s+name=(\S+))?`
PR #280 was updated to reflect this.

Final action vocabulary (all five values):

| Action | Meaning |
|--------|---------|
| `actor` | Message boundary, remote dispatch |
| `flow` | Sub-flow, compile recursively |
| `unfold` | Expand function body into current flow |
| `inline` | Keep call as-is in router code |
| `config` | Strip and extract infrastructure metadata |

Note: `decompose` (old name) → `unfold`. PR #280 implements `actor` and `inline`;
`flow`, `unfold`, `config` are recognized but raise "not yet implemented".

## Original context

See [1mhs] - it supports custom decorators `@actor`.
See [1fmi] - it wants to support tenacity `@retry`.

## References

- `.aint/aints/asya-lab/research-compiler-knowledge-base.md` — full treat-as
  system design, five action values, extraction mechanism
- `.aint/aints/asya-lab/rfc.md` §9.1 — compiler rules summary
