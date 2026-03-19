# RFC: Compiler Simplification — Yield-Analysis-First Architecture

## Status

Draft

## Problem

The flow compiler's IR mirrors Python AST too closely. 12 node types
(`ActorCall`, `Mutation`, `Condition`, `WhileLoop`, `Break`, `Continue`,
`TryExcept`, `ExceptHandler`, `Raise`, `FanOutCall`, `WithBlock`, `Return`)
create an explosion of special cases across three downstream modules:

- **grouper.py** (~715 lines): converts tree IR to Router graph, managing
  convergence labels, loop-back labels, try/except (4 router types per
  try block), fan-out/fan-in, with-block wrapping
- **codegen.py** (~637 lines): generates Python from Router objects, with
  10+ specialized methods (`_generate_try_enter_router`,
  `_generate_except_dispatch_router`, `_generate_loop_back_router`, etc.)
- **dotgen.py** (~780 lines): generates DOT from Router objects, duplicating
  the same branching logic as codegen

Every new Python construct (context managers, decorators, match statements)
requires changes across all three modules. The IR is a compilation
intermediate that disappears after code generation — it cannot be reused
for standalone actor visualization or manifest generation.

### Root cause

The IR represents **Python syntax** (if/else, while, try/except) rather than
**actor mesh semantics** (send to actor, conditional routing). The grouper
then does heavy lifting to translate syntax into routing — but the routing
is what matters. All Python constructs ultimately reduce to "send payload
to an actor", which is the actual semantic of the mesh.

## Design Principles

1. **Flows are sugar** — they instantiate AsyncActors (handler + config + name)
   labeled with `asya.sh/flow=<name>`. No Flow CRD exists. AsyncActor is
   the first-class citizen.

2. **Yields are the source of truth** — graph topology comes from static
   analysis of yield ABI events in handler code. Both flow-generated routers
   and user-written handlers produce the same yield patterns.

3. **IR is a deployment graph, not a compilation intermediate** — it lives
   _after_ code generation, not before. It's a flat directed graph of actor
   nodes and edges, not a tree of Python AST nodes.

4. **Graph is informational** — the DOT/SVG output is for users to debug
   their actor mesh. Complex conditions like `if complex_condition(payload)`
   are shown as edge labels — users will understand them. Dynamic routing
   (`yield "SET", ".route.next", [variable]`) produces unresolvable edges
   that are simply omitted.

5. **Actor config, not graph structure** — error handling (on_error),
   retry, timeout are actor-level configuration, not control flow nodes
   in the graph.

## Proposed Architecture

### Two-phase pipeline

```
Phase 1 (compile):     flow.py  ──────────>  routers.py
                                              (Python handlers with yield ABI)

Phase 2 (analyze):     routers.py       ─┐
                       handler_*.py      ─┤──>  IR graph  ──>  manifests/
                       actor configs     ─┘        |            DOT/SVG
                                                   |            validation
                                              {nodes, edges}
```

**Phase 1** is the existing flow compiler, simplified. It transforms Python
control flow (if/else, while, try/except) into generator handlers that use
yield ABI for routing. The output is pure Python — no IR, no graph, just
handler code.

**Phase 2** is new. A yield analyzer scans _all_ Python handler files
(both flow-generated routers and user-written actors), extracts yield
patterns, and builds a flat directed graph. This graph feeds downstream
consumers: manifest generation, DOT visualization, validation.

### Phase 1: flow.py -> routers.py (simplified)

The compiler keeps Python syntax understanding but the output is simpler:
instead of building a tree IR and then converting it to Routers via the
grouper, it directly generates Python handler code. The grouper and its
convergence labels, loop counters, try counters disappear.

What the compiler still does:
- Parse `@flow`-decorated functions
- Recognize `p = handler(p)` as actor calls
- Transform `if/else` into conditional `yield "SET", ".route.next", [...]`
- Transform `while` into self-referencing routing (router appends itself to route.next)
- Transform `break`/`continue` into route overwrite/skip
- Transform `try/except` into `_on_error` header setup + dispatch routing
- Transform `return` into route-to-end
- Apply DSL rules (treat-as: config, inline, etc.)

What the compiler no longer does:
- Build an IR tree of 12 node types
- Run a grouper to convert IR tree -> Router list
- Manage convergence labels, loop-exit labels, loop-back labels
- Track separate router types (is_try_enter, is_try_exit, is_except_dispatch, is_reraise, is_loop_back, is_fan_out)

The output format remains the same: `routers.py` files with async generator
functions that yield ABI commands. The generated code is identical to today's
output — only the internal pipeline changes.

### Phase 2: yield analysis -> IR graph

The yield analyzer is a new module that statically analyzes Python handler
files to extract routing information from yield statements.

#### Analyzable yield patterns

| Pattern | Edge type | Example |
|---|---|---|
| `yield "SET", ".route.next", ["actor_a", "actor_b"]` | Explicit edge(s) to named actors | Conditional routing, loop-back |
| `yield "SET", ".route.next[:0]", [resolve("x")]` | Prepend edge to resolved handler | Sequential routing |
| `yield "SET", ".route.next", []` | Terminal (no outgoing edges) | End router, break |
| `yield payload` / `yield p` | Implicit edge to whatever route.next contains | Pass-through |
| `yield "FLY", {...}` | No edge (ephemeral upstream) | Streaming tokens |
| `yield "SET", ".headers._on_error", resolve("x")` | Error edge to dispatch router | Try-enter |

#### Condition extraction

When a yield appears inside an `if/else` block, the analyzer captures the
condition as an edge label:

```python
if p['type'] == 'A':
    yield "SET", ".route.next", [resolve("handler_type_a")]
else:
    yield "SET", ".route.next", [resolve("handler_type_b")]
```

Produces edges:
- `router -> handler_type_a` with label `p['type'] == 'A'`
- `router -> handler_type_b` with label `else`

Complex conditions (`if complex_condition(payload)`) are kept as-is in the
label — the graph is informational, not executable.

#### Unresolvable patterns (skipped)

```python
next_actor = resolve(payload["type"])  # runtime-computed
yield "SET", ".route.next", [next_actor]
```

Dynamic routing where the target is a variable (not a string literal or
`resolve("literal")` call) produces no edge in the graph. The node is
marked with an `unresolved_routing: true` flag.

Future: the DSL rules engine (aint `1fmi`) will allow users to teach the
compiler about custom functions' semantics. For example, a user-defined
`resolve_by_type(payload)` could be annotated with a rule that maps its
return values to specific actor names.

### IR graph format

The IR is a flat directed graph with two node types:

```python
@dataclass
class Node:
    name: str                    # actor/router name
    type: str                    # "actor" | "router"
    handler: str                 # Python handler function name
    source_file: str             # path to .py file
    lineno: int                  # line number in source
    config: dict | None = None   # actor config (retry, timeout, on_error)

@dataclass
class Edge:
    source: str                  # node name
    target: str                  # node name
    condition: str | None = None # edge label (if condition, "else", etc.)
    edge_type: str = "route"     # "route" | "error" | "fanout"

@dataclass
class MeshGraph:
    nodes: list[Node]
    edges: list[Edge]
    flow_name: str | None = None # set if graph came from a flow
    unresolved: list[str] = field(default_factory=list)  # nodes with dynamic routing
```

Properties:
- Nodes map 1:1 to AsyncActor manifests
- Edges map to `route.next` relationships
- The graph is the single source of truth for both DOT generation and
  manifest generation
- Both flow-generated routers and standalone actors produce the same
  graph format

### Downstream consumers

The IR graph feeds three consumers:

1. **DOT/SVG generator** — reads `MeshGraph`, produces Graphviz DOT.
   Much simpler than today's dotgen (which interprets Router objects
   with 15+ boolean flags). Just iterate nodes and edges.

2. **Manifest generator** — reads `MeshGraph`, produces AsyncActor YAML
   manifests. Each node becomes an AsyncActor spec with handler reference,
   routing config, and labels.

3. **Validation** — checks graph properties: connectivity (no orphan nodes),
   reachability (all nodes reachable from start), cycle detection (loops
   must have a break/condition exit), fan-out/fan-in consistency.

### Standalone actor visualization

A key benefit: standalone actors (not part of any flow) can be visualized
by the same pipeline. The yield analyzer reads their handler code, extracts
routing edges, and produces a `MeshGraph`. Users don't need to write a
flow to see their actor topology — they just run:

```bash
asya flow graph handler_a.py handler_b.py handler_c.py
```

This scans the handlers, builds the graph from yield analysis, and outputs
DOT/SVG.

## Migration strategy

### Phase 1: New yield analyzer alongside existing pipeline

Add the yield analyzer as a new module (`analyzer.py`) that takes Python
handler files and produces `MeshGraph`. Wire it into the existing
`asya flow compile` as an optional `--graph` flag. The existing
parser -> IR -> grouper -> codegen pipeline continues to work unchanged.

This validates the yield analysis approach without breaking anything.

### Phase 2: New DOT generator from MeshGraph

Write a new DOT generator that reads `MeshGraph` instead of `Router` objects.
Run it in parallel with the existing dotgen to verify output equivalence.
Once validated, replace the old dotgen.

### Phase 3: Simplify the compiler internals

With the yield analyzer proven, simplify the compiler's internal pipeline.
The parser can emit code more directly (fewer intermediate representations).
The grouper's complexity reduces because it no longer needs to produce
Router objects with 15+ fields — it just needs to produce correct Python
handler code.

### Phase 4: Manifest generation from MeshGraph

Add manifest generation: `MeshGraph` -> AsyncActor YAML. This replaces
the current approach where manifests are hand-crafted or generated by
separate tooling.

## Relationship to existing work

- **aint `1fmi` (rules engine)**: The rules engine teaches the compiler
  about custom function semantics. In the new architecture, rules inform
  both Phase 1 (how to compile custom constructs) and Phase 2 (how to
  resolve dynamic routing targets during yield analysis).

- **aint `pyn3` (inline comment overrides)**: `# asya: treat-as-inline`
  annotations work in both architectures. They inform the compiler how
  to generate code, and the yield analyzer sees the result.

- **aint `bvs4` (SVG instead of PNG)**: Output format is orthogonal to
  the architecture change. The new DOT generator produces the same DOT
  format.

## What disappears

| Current component | Status |
|---|---|
| `ir.py` (12 node types) | Replaced by `MeshGraph` (2 types: Node, Edge) |
| `grouper.py` (~715 lines) | Eliminated. Compiler emits code directly. |
| `dotgen.py` (~780 lines) | Replaced by graph-based DOT generator (~200 lines estimated) |
| `Router` dataclass (15+ fields) | Eliminated. No intermediate Router representation. |
| Convergence labels | Eliminated. Direct routing in generated code. |
| Try counter / loop counter / fanout counter | Eliminated. Naming embedded in codegen. |

## What stays

| Component | Status |
|---|---|
| `parser.py` | Retained but simplified. Emits code more directly. |
| `codegen.py` | Retained but simplified. Fewer specialized methods. |
| `rules.py` | Retained and extended. Informs both compilation and analysis. |
| `compiler.py` | Retained. Orchestrates the pipeline. |
| Generated `routers.py` format | Unchanged. Same yield ABI patterns. |
| `resolve()` function in generated code | Unchanged. |

## Open questions

1. **Scope of Phase 1 simplification**: How aggressively should we simplify
   the parser/codegen in Phase 3? Options range from "just delete the grouper
   and have the parser emit code directly" to "keep the grouper but make
   Router a much simpler dataclass".

2. **Graph persistence format**: Should `MeshGraph` be serialized to disk
   (JSON/YAML) alongside `routers.py`, or computed on-demand from handler
   files? On-demand is simpler but slower for large meshes.

3. **Scope of standalone actor analysis**: How much Python should the yield
   analyzer understand? Just top-level yields? Yields inside if/else?
   Yields inside nested functions? Recommendation: if/else yields (for
   condition labels) but not deeper nesting.
