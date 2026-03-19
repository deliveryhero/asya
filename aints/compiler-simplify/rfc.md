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

3. **No IR** — there is no intermediate representation. Actors (handler
   code + manifests) are the representation. The "graph" is an ephemeral
   view computed on-demand by scanning handler yields — not a persisted
   data structure, not a first-class concept. If actors map 1:1 to what
   an IR would contain, the IR is redundant. The transient graph dict
   can be dumped to JSON/YAML via `--debug-graph` for debugging, but
   this is a debug artifact, not a pipeline stage.

4. **Graph is informational** — the DOT/SVG output is for users to debug
   their actor mesh. Complex conditions like `if complex_condition(payload)`
   are shown as edge labels — users will understand them. Dynamic routing
   (`yield "SET", ".route.next", [variable]`) produces unresolvable edges
   that are simply omitted.

5. **Actor config, not graph structure** — error handling (on_error),
   retry, timeout are actor-level configuration, not control flow nodes
   in the graph.

## User Workflow and Project Model

### Python-native resolution

The compiler uses the project's Python interpreter to resolve all
functions, handlers, imports, and decorators. This is a **critical
decision**: asya is not a purely syntactical tool. It imports and
inspects Python objects at compile time.

**From SDK/notebook**: use the current Python interpreter (trivial).

**From CLI**: detect the project's Python environment automatically:
1. Check for active virtualenv (`$VIRTUAL_ENV`)
2. Check for `uv` project (`.venv/`, `pyproject.toml` with `[tool.uv]`)
3. Check for `poetry` project (`poetry.lock`)
4. Fall back to system Python

Override with `--python /path/to/python`.

This means the compiler can resolve `from external_pack import process`
and inspect its decorators — even if `external_pack` is a pip-installed
third-party package.

### Actor identity

Actor identity = **resolved Python handler** + **infra configuration**.

One handler function can produce multiple deployed actor entities:

```
foo_bar()  ──>  foo-bar          (default config)
           ──>  foo-bar-heavy    (16 CPU, GPU, different retry policy)
           ──>  foo-bar-staging  (staging env vars)
```

- **Handler naming**: Python convention with underscore (`foo_bar`)
- **Actor naming**: Kubernetes convention with dash (`foo-bar-1`)
- **Mapping is 1:N**: one handler, multiple actor CRDs with different configs

The flow DSL sees only the handler function. The 1:N expansion happens
at the manifest level — controlled by `.asya/config.yaml` or kustomize
overlays.

### Separation of concerns

One of Asya's two core advantages: clear separation between business
logic (DS-owned) and infra configuration (platform-owned).

| Layer | Owner | Content | Format |
|---|---|---|---|
| Handler code | DS | Business logic, routing, error handling | Python (.py) |
| Flow DSL | DS | Control flow composition of handlers | Python (.py) |
| Generated routers | Compiler | CPS-transformed control flow | Python (.py) |
| Generated manifests | Compiler | Base XR specs from extracted config | YAML (kustomize base/) |
| Overlay manifests | Platform | Resource limits, replicas, secrets | YAML (kustomize common/) |

Handlers/flows contain ONLY business-logic-level information. The
compiler generates static XR manifests from pre-configured templates
into a kustomize `base/` layer. Platform engineers adjust these in
`common/` overlay — they never touch the generated base.

### Project structure

```
repo/
├── .asya/config.yaml              # repo-level config
├── team1/
│   ├── .asya/config.yaml          # team override
│   ├── pyproject.toml             # Python deps (external_pack1, etc.)
│   ├── pack1/
│   │   └── actors/
│   │       ├── handler_a.py       # standalone handler
│   │       └── handler_b.py
│   ├── pack2/
│   │   └── flows/
│   │       ├── my_flow.py         # @flow function
│   │       └── compiled/          # generated router code (Python, lives with code)
│   │           └── my_flow/
│   │               └── routers.py
│   └── deploy/
│       └── my_flow/               # generated + overlay manifests (YAML, lives with infra)
│           ├── base/              # generated by compiler (don't edit)
│           │   ├── kustomization.yaml
│           │   ├── handler-a.yaml
│           │   ├── handler-b.yaml
│           │   └── router-line-14-if.yaml
│           └── common/            # platform overlay (edit freely)
│               ├── kustomization.yaml
│               └── patches/
│                   └── resources.yaml
```

Key: **generated code stays with Python code** (`compiled/`),
**generated manifests stay with infra** (`deploy/`). Both paths are
configurable in `.asya/config.yaml`.

### .asya/config.yaml

```yaml
# Python environment (auto-detected if omitted)
python: .venv/bin/python

# Handler-to-image mapping
images:
  default: ghcr.io/team/actors:latest
  overrides:
    pack1.actors.handler_a: ghcr.io/team/gpu-actors:latest
    external_pack1.process: ghcr.io/partner/ml-models:v2

# Output paths (relative to .asya/ location)
output:
  compiled: "{flow_dir}/compiled/{flow_name}/"   # routers.py
  manifests: "deploy/{flow_name}/base/"           # XR YAML

# Compiler rules (extended from aint 1fmi)
rules:
  - symbol: "tenacity.retry"
    treat_as: config
    extract:
      max_attempt_number: spec.resiliency.retry.maxRetries
  - symbol: "asyncio.timeout"
    treat_as: config
    extract:
      delay: spec.resiliency.actorTimeout
```

### CLI interface

The user passes **file paths** (not flow names or module paths).
File paths are unambiguous, tab-completable, and don't require
discovery or import resolution to locate.

```bash
# Compile a flow: produces routers.py + manifests
asya compile pack2/flows/my_flow.py

# Compile a standalone handler: produces manifest only (no code transform)
asya compile pack1/actors/handler_a.py

# Compile everything in a directory
asya compile pack2/flows/

# Visualize: yield-analysis across handler files → DOT/SVG
asya graph pack2/flows/compiled/my_flow/routers.py pack1/actors/*.py

# Visualize a compiled flow (knows where routers are from config)
asya graph pack2/flows/my_flow.py

# Debug: dump transient graph dict
asya graph --debug-graph pack2/flows/my_flow.py
```

Config resolution: walk up from the target file to find the nearest
`.asya/config.yaml`. Merge with parent configs (repo-level as base,
team-level as override).

### SDK interface

```python
from asya_lab import compile, graph

# From notebook or script — uses current Python interpreter
result = compile("pack2/flows/my_flow.py")
# result.routers_code: str           (routers.py content)
# result.manifests: list[dict]       (AsyncActor XR specs)
# result.handlers: list[HandlerInfo] (resolved handler metadata)

dot = graph("pack2/flows/my_flow.py")
# dot: str (Graphviz DOT)
```

## Proposed Architecture

### Two-phase pipeline

```
                                    ┌──>  compiled/routers.py   (with Python code)
Phase 1 (compile):  flow.py  ──────┤
                                    └──>  deploy/base/*.yaml    (with infra)

Phase 2 (graph):    routers.py      ─┐
                    handler_*.py     ─┤──>  DOT/SVG, validation
                    (resolved via    ─┘
                     project Python)
```

**Phase 1** is the existing flow compiler, simplified. It transforms Python
control flow (if/else, while, try/except) into generator handlers that use
yield ABI for routing. The output is pure Python — no IR, no graph, just
handler code.

**Phase 2** is new. A yield analyzer scans _all_ referenced Python handler files
(both flow-generated routers and user-written actors), extracts yield
patterns, and directly produces outputs: DOT/SVG visualization, manifests,
validation reports. Internally it builds a transient `{nodes, edges}` dict
to pass between analysis and rendering, but this is a local implementation
detail — not a persisted or first-class data structure.

### Phase 1: flow.py -> routers.py + manifests/ (simplified)

The compiler keeps Python syntax understanding but the output is simpler:
instead of building a tree IR and then converting it to Routers via the
grouper, it directly generates Python handler code. The grouper and its
convergence labels, loop counters, try counters disappear.

The compiler produces two outputs:

1. **routers.py** — Python handler code with yield ABI (same as today)
2. **manifests/** — AsyncActor XR YAML for each actor in the flow

Manifests capture infra-level configuration that the compiler extracts
from the flow source:

- **Env vars**: `os.environ["KEY"]` references → `spec.env[].value`
- **Retry config**: `@retry(max_attempts=3)` or `tenacity.retry(...)` →
  `spec.resiliency.policies.*`
- **Timeout**: `asyncio.timeout(30)` → `spec.resiliency.timeout.*`
- **Actor names and labels**: handler name → `metadata.name`,
  `asya.sh/flow` label
- **Handler reference**: function path → `spec.handler`

This is where the rules engine (aint `1fmi`) plugs in: `treat-as: config`
rules tell the compiler which decorators/context managers to extract
configuration from and where to place the extracted values in the manifest.

The `extracted_configs` list already exists in the parser today — this
extends it to produce actual YAML output.

What the compiler still does:
- Parse `@flow`-decorated functions
- Recognize `p = handler(p)` as actor calls
- Transform `if/else` into conditional `yield "SET", ".route.next", [...]`
- Transform `while` into self-referencing routing (router appends itself to route.next)
- Transform `break`/`continue` into route overwrite/skip
- Transform `try/except` into resiliency configuration
- Transform `return` into route-to-end
- Apply DSL rules (treat-as: config, inline, etc.)
- **NEW**: Extract actor configuration and emit AsyncActor manifests

What the compiler no longer does:
- Build an IR tree of 12 node types
- Run a grouper to convert IR tree -> Router list
- Manage convergence labels, loop-exit labels, loop-back labels
- Track separate router types (is_try_enter, is_try_exit, is_except_dispatch, is_reraise, is_loop_back, is_fan_out)

The handler code output format remains the same: `routers.py` files with
async generator functions that yield ABI commands. The generated code is
identical to today's output — only the internal pipeline changes.

### Phase 2: yield analysis -> outputs

The yield analyzer is a new module that statically analyzes Python handler
files to extract routing information from yield statements. It produces
DOT/SVG and manifests directly — no separate IR layer.

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

### Internal representation (transient)

The yield analyzer internally builds a lightweight dict to pass between
analysis and rendering. This is NOT an IR — it's a local data structure
inside the analyzer function, equivalent to a function's local variables:

```python
# Internal to the analyzer — not exported, not persisted
nodes: list[dict]   # [{"name": "...", "handler": "...", "source": "...", "lineno": N}, ...]
edges: list[dict]   # [{"source": "...", "target": "...", "condition": "...", "type": "route"}, ...]
```

The analyzer function signature is simply:

```python
def analyze_handlers(files: list[Path]) -> str:
    """Scan handler files, return DOT string."""
    ...

def analyze_handlers_manifests(files: list[Path], config: dict) -> list[dict]:
    """Scan handler files, return AsyncActor manifest dicts."""
    ...
```

No `MeshGraph` class. No `Node`/`Edge` dataclasses exported from the module.
The transient dict lives and dies inside the function call.

### Downstream outputs

Phase 2 (yield analysis) produces:

1. **DOT/SVG** — iterate nodes/edges, emit Graphviz DOT.
   Much simpler than today's dotgen (which interprets Router objects
   with 15+ boolean flags).

2. **Validation** — connectivity checks, reachability, cycle detection.
   Reported as warnings/errors during analysis, not as a separate pass.

3. **Debug graph dump** (`--debug-graph`) — JSON/YAML dump of the
   transient `{nodes, edges}` dict for troubleshooting.

Manifests are produced by Phase 1 (compiler), not Phase 2 (analyzer).
The compiler knows actor configuration (retry, timeout, env vars) from
parsing the flow source. The analyzer only knows routing topology from
yields.

### Standalone actor visualization

A key benefit: standalone actors (not part of any flow) can be visualized
by the same pipeline. The yield analyzer reads their handler code, extracts
routing edges, and produces DOT directly. Users don't need to write a
flow to see their actor topology — they just run:

```bash
asya flow graph handler_a.py handler_b.py handler_c.py
```

This scans the handlers, builds the graph from yield analysis, and outputs
DOT/SVG.

## Migration strategy

### Phase 1: New yield analyzer alongside existing pipeline

Add the yield analyzer as a new module (`analyzer.py`) that takes Python
handler files and produces DOT output. Wire it into the existing
`asya flow compile` as an optional `--graph` flag. The existing
parser -> IR -> grouper -> codegen pipeline continues to work unchanged.

This validates the yield analysis approach without breaking anything.
Run both old dotgen and new analyzer on the same compiled routers to
verify output equivalence.

### Phase 2: Replace dotgen with yield-analysis-based generator

Once the analyzer produces equivalent DOT output, replace `dotgen.py`
(~780 lines) with the analyzer's DOT output. The old dotgen (which
reads Router objects) is deleted.

### Phase 3: Simplify the compiler internals

With DOT generation decoupled from the compiler, simplify the internal
pipeline. The parser can emit code more directly (fewer intermediate
representations). The grouper's complexity reduces because it no longer
needs to produce Router objects with 15+ fields — it just needs to
produce correct Python handler code.

### Phase 4: Manifest generation in compiler

Add manifest output to Phase 1. The compiler already extracts config
via `treat-as: config` rules (`extracted_configs`). Extend this to
produce AsyncActor XR YAML alongside `routers.py`. Each actor in the
flow gets a manifest with handler reference, labels, and extracted
configuration (retry, timeout, env vars).

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
| `ir.py` (12 node types) | Eliminated. No IR. Actors are the representation. |
| `grouper.py` (~715 lines) | Eliminated. Compiler emits code directly. |
| `dotgen.py` (~780 lines) | Replaced by yield-analysis DOT generator (~200 lines estimated) |
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

1. **Scope of Phase 3 simplification**: How aggressively should we simplify
   the parser/codegen? Options range from "just delete the grouper and have
   the parser emit code directly" to "keep the grouper but make Router a
   much simpler dataclass".

2. **Scope of standalone actor analysis**: How much Python should the yield
   analyzer understand? Just top-level yields? Yields inside if/else?
   Yields inside nested functions? Recommendation: if/else yields (for
   condition labels) but not deeper nesting.
