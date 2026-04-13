---
title: Support more compiler constructs
status: merged
priority: 2
children:
  - 1fmik
  - 1mhsr
  - 1mhs8
  - 1mhsi
  - 1mhsn
  - 1ob9s
  - 1oj43
  - 1opdl
  - 2t1q3
  - 36g4o
  - kd2iq
  - n67c9
  - pyn38
  - srn2x
  - xx8tk
  - 1oimd
  - 20c9j
  - mm2u7
  - w1brx
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
