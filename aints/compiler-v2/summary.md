---
title: Support more compiler constructs
priority: 2
---

Expand the Flow DSL compiler to handle additional Python constructs that map
cleanly to the actor-mesh execution model. Each construct either compiles to
router logic or is explicitly rejected with a clear message.

**Design invariant**: all mutable state lives in the payload dict (`p`). No
local variables cross actor boundaries — the parser enforces this structurally.

## Constructs in scope

| Construct | Compilation target | Priority |
|-----------|-------------------|----------|
| `del p["key"]` | Mutation (payload key removal) | P3 |
| `assert expr` | Guard (early exit / error on violation) | P3 |
| `import` / `from import` | Handler module references | P3 |
| `match` / `case` | Conditional routing (like if/elif) | P3 |
| `async for e in actor(p)` | Fan-in from multi-yield actor | P2 |
| Arbitrary param name | `_ParamNormalizer` already handles; lift `VALID_PARAM_NAMES` | P2 |
