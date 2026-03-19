---
title: "Phase 1: Core pipeline rewrite (parser + codegen + analyzer + graphgen)"
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/compiler-simplify/dlad.phase-1-core-pipeline-rewrite-parser-codegen-analyzer
  - branch:compiler-simplify/dlad.phase-1-core-pipeline-rewrite-parser-codegen-analyzer
dependencies:
  - 7179
---


## Overview

Replace the entire internal compiler pipeline in one atomic change.
Delete ir.py (88 lines), grouper.py (715 lines), dotgen.py (782 lines).
Create analyzer.py (~200 lines) and graphgen.py (~150 lines).
Rewrite parser.py and codegen.py.

Net result: ~3206 lines → ~1410 lines (-56%).

## What to implement

### 1. parser.py — rewrite to emit 5 operation types

Replace 12 IR node types with 5 operation dataclasses (defined in parser.py, no separate ir.py):

```python
@dataclass
class ActorCall:
    name: str           # handler function FQN
    lineno: int
    source_file: str

@dataclass
class Mutation:
    code: str           # raw Python code
    lineno: int

@dataclass
class Conditional:
    test: str           # Python expression
    true_branch: list[Operation]
    false_branch: list[Operation]
    lineno: int

@dataclass
class Loop:
    test: str | None    # None = while True (NO built-in max_iterations guard)
    body: list[Operation]
    lineno: int

@dataclass
class FanOut:
    target_key: str
    pattern: str        # "comprehension" | "literal" | "gather"
    actor_calls: list[tuple[str, str]]
    iter_var: str | None
    iterable: str | None
    lineno: int

Operation = ActorCall | Mutation | Conditional | Loop | FanOut
```

Eliminated types and where they went:
- Break → codegen emits `yield "SET", ".route.next", [resolve(convergence)]`
- Continue → codegen emits `yield "SET", ".route.next", [resolve(self)]`
- Return → codegen emits routing to exit actor
- Raise → manifest config (sidecar routes to error handler)
- TryExcept → parser extracts error types → `resiliency_rules` in ParseResult (aint 7179 policies)
- ExceptHandler → folded into resiliency_rules
- WithBlock → `treat_as: config` → manifest, `treat_as: inline` → Mutation

**IMPORTANT**: `yield "SET", ".route.next", []` means ABORT (send to x-sink), NOT break.

Unmatched constructs (try/except, with-block, decorators without compiler rules) → compile error with guidance.

Output:
```python
@dataclass
class ParseResult:
    flow_name: str
    operations: list[Operation]
    actors: list[ActorRef]
    resiliency_rules: list[dict]    # from try/except
    extracted_configs: list[dict]
    ignore_decorators: list[str]    # FQNs for ASYA_IGNORE_DECORATORS
    imports: list[str]
    constants: list[str]
```

### 2. codegen.py — direct code generation, no grouper

Rewrite to walk operation types directly and generate router functions.
No Router dataclass. No grouper intermediate.

- ActorCall → `_next.append(resolve("handler_name"))`
- Mutation → raw code inserted
- Conditional → `if test: ... else: ...` with routing in branches
- Loop → self-referencing router
- FanOut → multi-yield pattern

**Invariant P13: one decision per router.** Each generated router function
has at most one level of if/else. Nested control flow in flow DSL produces
a CHAIN of routers, not nested blocks in one function. This keeps the
yield analyzer trivial.

### 3. analyzer.py — NEW module (~200 lines)

Static yield analysis using `ast.parse()` on Python handler files.

Internal function `_extract_yield_edges(source, handler_name)`:
1. Parse handler source with `ast.parse()`
2. Walk AST to find yield expressions matching ABI patterns
3. Classify: SET route.next, SET headers, FLY, plain yield
4. Extract targets from string literals or `resolve()` calls
5. Walk up AST for enclosing `if` → capture condition as edge label
6. Return edge dicts `{from, to, label, type}`

Three handler categories:
- Generated routers (routers.py): full analysis, all patterns analyzable
- User handlers (project source): best-effort via `inspect.getsource()`
- External packages (site-packages): opaque node if no source available

Analyzable yield patterns:
| Pattern | Edge type |
|---|---|
| `yield "SET", ".route.next", ["actor_a"]` | Explicit edge to named actor |
| `yield "SET", ".route.next[:0]", [resolve("x")]` | Prepend edge |
| `yield "SET", ".route.next", []` | Abort — terminal node (x-sink) |
| `yield payload` | Implicit pass-through edge |
| `yield "FLY", {...}` | No routing edge |

Four-step merge algorithm:
1. Parse generated routers → `_extract_yield_edges()` → routing chains
2. Parse user handlers → `_extract_yield_edges()` → override edges
3. Parse manifests → `resiliency.rules[*].thenRoute` → error edges
4. Merge: chains + overrides + error edges (override: true on user edges)

Output:
```python
@dataclass
class GraphData:
    nodes: list[dict]   # {"id", "flow_role", "label", "sources"}
    edges: list[dict]   # {"from", "to", "label", "type", "override"}
    groups: list[dict]  # {"id", "nodes"}
```

### 4. graphgen.py — NEW module (~150 lines)

Three renderers consuming GraphData:
```python
def to_dot(data: GraphData, flow_name: str) -> str: ...
def to_mermaid(data: GraphData, flow_name: str) -> str: ...
def to_json(data: GraphData, flow_name: str) -> dict: ...
```

Each ~50 lines. Replaces 782-line dotgen.py.

### 5. Delete old modules

- ir.py (88 lines) — types moved to parser.py
- grouper.py (715 lines) — logic absorbed by codegen.py
- dotgen.py (782 lines) — replaced by graphgen.py

### Unit tests

- Parser: verify 5 operation types from various flow patterns
- Codegen: verify one-decision-per-router invariant, nested if/while → router chains
- Analyzer: _extract_yield_edges for each ABI pattern, three handler categories, merge algorithm
- Graphgen: DOT/Mermaid/JSON output for simple and complex graphs

## Key files

- `src/asya-lab/asya_lab/flow/parser.py` (rewrite)
- `src/asya-lab/asya_lab/flow/codegen.py` (rewrite)
- `src/asya-lab/asya_lab/flow/analyzer.py` (new)
- `src/asya-lab/asya_lab/flow/graphgen.py` (new)
- `src/asya-lab/asya_lab/flow/ir.py` (delete)
- `src/asya-lab/asya_lab/flow/grouper.py` (delete)
- `src/asya-lab/asya_lab/flow/dotgen.py` (delete)

## References

- RFC: `.aint/aints/compiler-simplify/rfc.md` (sections: Operation types, codegen.py, analyzer.py, graphgen.py)
- Design decisions: `.aint/aints/compiler-simplify/design-decisions.md` (P1-P13)
- Aint 7179: policy-based error handling (try/except → resiliency.rules)
- Existing compiled examples: `examples/flows/compiled/` (verify parity)
