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

### Flow is always the entry point

Flows are the unit of deployment, exposure, and visualization. There is
no standalone actor visualization without a flow. Even a single-actor
pipeline requires a flow wrapper:

```python
@flow
async def classify_pipeline(p):
    p = await classify(p)
    return p
```

This ensures every actor in the mesh belongs to a flow (has
`asya.sh/flow=<name>` label), can be exposed to the gateway, and
appears in the flow graph.

### User environments

Three primary environments, all using the same compiler:

| Environment | Trigger | Compilation model |
|---|---|---|
| **Python script/package** | `asya compile flow.py` (CLI) | Batch: full recompile, write files |
| **Jupyter notebook** | `compile("flow.py")` or `%asya compile` | Explicit: DS re-runs compile cell |
| **IDE (VSCode)** | File save triggers extension | Reactive: extension calls compile on save |

Interactive mode (`asya serve`): runs HTTP server, provides REST API for
UI/extensions, stores `FlowInfo` in memory, dumps to files for persistence.
File-watching is for `.py` files; notebook cells require explicit re-run.
Anywidget integration for reactive notebooks is a future investigation.

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
third-party package. External packages get yield analysis if source is
available in site-packages; otherwise they appear as opaque nodes in
the graph (best-effort).

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
at the manifest level — DS clicks actor nodes in the graph UI to
customize name/config, and these changes write to kustomize overlays.
The config editing UI reads the AsyncActor XRD's OpenAPI schema to
determine which fields are editable.

### Separation of concerns

One of Asya's two core advantages: clear separation between business
logic (DS-owned) and infra configuration (platform-owned).

| Layer | Owner | Content | Format |
|---|---|---|---|
| Handler code | DS | Business logic, routing, error handling | Python (.py) |
| Flow DSL | DS | Control flow composition of handlers | Python (.py) |
| Generated routers | Compiler | CPS-transformed control flow | Python (.py) |
| Generated manifests | Compiler | Base XR specs from extracted config | YAML (kustomize base/) |
| Overlay manifests | Platform/DS | Resource limits, replicas, secrets | YAML (kustomize common/) |

Handlers/flows contain ONLY business-logic-level information. The
compiler generates static XR manifests from pre-configured templates
into a kustomize `base/` layer. Platform engineers adjust these in
`common/` overlay — they never touch the generated base.

### Config extraction and decorator stripping

When compiler rules mark a decorator as `treat-as: config` (e.g.,
`@retry(max_attempts=3)`), the compiler:

1. **Extracts** the config value → places in manifest
   (`spec.resiliency.retry.maxRetries: 3`)
2. **Records stripping** → adds `ASYA_IGNORE_DECORATORS` env var to
   the actor's manifest with a comma-separated list of FQN decorators
   (e.g., `tenacity.retry,asyncio.timeout`)

The runtime reads `ASYA_IGNORE_DECORATORS` and strips these decorators
when loading the handler. The original handler source code is **never
modified** by the compiler.

### Project structure

```
repo/
├── .asya/config.yaml              # repo-level config
├── team1/
│   ├── .asya/config.yaml          # team override
│   ├── pyproject.toml             # Python deps (external_pack1, etc.)
│   ├── pack1/
│   │   └── actors/
│   │       ├── handler_a.py       # handler (has yield ABI internally)
│   │       └── handler_b.py
│   ├── pack2/
│   │   └── flows/
│   │       ├── my_flow.py         # @flow function
│   │       └── compiled/          # generated router code (lives with code)
│   │           └── my-flow/       # flow name in kebab-case
│   │               ├── routers.py
│   │               ├── graph.json
│   │               ├── flow.dot
│   │               ├── flow.mmd
│   │               └── flow.svg
│   └── deploy/
│       └── my-flow/               # generated + overlay manifests (lives with infra)
│           ├── base/              # generated by compiler (don't edit)
│           │   ├── kustomization.yaml
│           │   ├── handler-a.yaml
│           │   ├── handler-b.yaml
│           │   └── router-line-14-if.yaml
│           └── common/            # overlay (edit freely, never overwritten)
│               ├── kustomization.yaml
│               └── patches/
│                   └── resources.yaml
```

Key: **generated code stays with Python code** (`compiled/`),
**generated manifests stay with infra** (`deploy/`). Both paths are
configurable in `.asya/config.yaml`. Directory names use flow name
in kebab-case.

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
  compiled: "{flow_dir}/compiled/{flow_name}/"   # routers.py + graph.json
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
      delay: spec.resiliency.timeout.actor
```

### CLI interface

The user passes **file paths** (not flow names or module paths).
File paths are unambiguous, tab-completable, and don't require
discovery or import resolution to locate.

```bash
# Primary command — produces everything
asya compile flow.py              # routers.py + manifests + graph.json + DOT + MMD + SVG
asya compile flow.py --no-plot    # skip SVG/DOT/MMD (graph.json still produced)
asya compile flows/               # compile all @flow files in directory
asya compile .                    # compile all @flow files in project

# Options
asya compile flow.py --python /path/to/python   # override interpreter
asya compile flow.py --config .asya/config.yaml # override config path
asya compile flow.py --dry-run                  # show what would be generated
asya compile flow.py --flow my-flow             # override inferred flow name
```

**Flow name inference**: `@flow def my_flow(p)` → `my-flow` (kebab-case).
Override with `--flow`. Printed to stdout for `export ASYA_LAB_FLOW=my-flow`.

```
$ asya compile pack2/flows/my_flow.py
[+] Compiled flow 'my-flow' (3 actors, 2 routers)
    routers:   pack2/flows/compiled/my-flow/routers.py
    manifests: deploy/my-flow/base/
    graph:     pack2/flows/compiled/my-flow/graph.json

export ASYA_LAB_FLOW=my-flow
```

**Recompilation**: always full recompile (idempotent). `base/` is
regenerated, `common/` is never overwritten. No `--force` flag needed —
`base/` and `compiled/` are compiler-owned and always overwritable.

Config resolution: walk up from the target file to find the nearest
`.asya/config.yaml`. Merge with parent configs (repo-level as base,
team-level as override).

### SDK interface

```python
from asya_lab import compile, FlowInfo

# Basic compilation (uses current Python interpreter)
result: FlowInfo = compile("pack2/flows/my_flow.py")

# With options
result = compile(
    "pack2/flows/my_flow.py",
    config=".asya/config.yaml",   # override config path
    flow_name="my-flow",          # override inferred name
    plot=True,                    # generate SVG (default True)
)

# FlowInfo attributes
result.flow_name         # "my-flow"
result.routers_path      # Path to generated routers.py
result.manifests_dir     # Path to generated base/ directory
result.graph             # dict (same as graph.json content)
result.dot               # str (DOT source)
result.mermaid           # str (Mermaid source)
result.svg               # str (SVG content) or None if plot=False
result.actors            # list[ActorInfo] — resolved actor metadata
result.warnings          # list[str]

# ActorInfo (extends existing templater.ActorInfo)
result.actors[0].name           # "handler-a" (K8s name, hyphens)
result.actors[0].handler        # "handler_a.classify" (in-container path)
result.actors[0].image          # "ghcr.io/team/actors:latest"
result.actors[0].flow_role      # "entry" | "exit" | "entryexit" | "router" | "actor"
result.actors[0].env            # [{"name": "KEY", "value": "val"}]
result.actors[0].is_generated   # True for routers, False for user handlers
result.actors[0].manifest_path  # Path to base/ manifest YAML
# Local-only (not in graph.json):
result.actors[0].source_file    # "pack1/handler_a.py"
result.actors[0].source_line    # 42
result.actors[0].handler_local  # "pack1.handler_a.classify" (local dev path)
```

SDK and CLI are mirrored — same pipeline, same outputs. SDK returns
`FlowInfo` object; CLI writes files and prints summary.

**Notebook usage:**
```python
# Jupyter cell
from asya_lab import compile
result = compile("flows/my_flow.py")

# Display graph inline
from IPython.display import SVG
SVG(result.svg)

# Interactive React Flow diagram (Phase 6 anywidget)
from asya_lab.widgets import FlowWidget
FlowWidget(result.graph)
```

**Programmatic flow definition (future):**
```python
from asya_lab import flow, compile

@flow
async def my_pipeline(p: dict) -> dict:
    p = await handler_a(p)
    if p["score"] > 0.8:
        p = await handler_b(p)
    return p

# Compile from function object (not file path)
result = compile(my_pipeline)
```

### graph.json schema

Minimal graph topology with links to sources (code + manifests).
Consumed by `asya serve` and React UI. Node and edge labels are
pure graph-theoretical labels with no semantic interpretation.

```json
{
  "flow": "my-flow",
  "nodes": [
    {
      "id": "handler-a",
      "flow_role": "entry",
      "label": "handler_a.classify",
      "image": "ghcr.io/team/actors:latest",
      "sources": {
        "code": "pack1/handler_a.py:5",
        "manifest": "deploy/my-flow/base/handler-a.yaml"
      }
    },
    {
      "id": "router-line-14",
      "flow_role": "router",
      "label": "p['type'] == 'A'",
      "sources": {
        "code": "compiled/my-flow/routers.py:42",
        "manifest": "deploy/my-flow/base/router-line-14.yaml"
      }
    }
  ],
  "edges": [
    {"from": "handler-a", "to": "router-line-14"},
    {"from": "router-line-14", "to": "handler-b", "label": "True"},
    {"from": "router-line-14", "to": "handler-c", "label": "False"},
    {"from": "handler-c", "to": "x-pause", "label": "p['needs_review']", "override": true}
  ],
  "groups": [
    {"id": "flow-b", "nodes": ["handler-c", "handler-d"]}
  ]
}
```

`override: true` on edges marks yield-analyzed routing that
overwrites flow-declared routing (scenario E: mixed flow + actor yields).

`asya serve` and CLI merge graph.json with source files and manifests
to produce the full interactive view.

### flow_role vocabulary

The `asya.sh/flow-role` label and graph.json `flow_role` field use
the same vocabulary:

| Value | Meaning |
|---|---|
| `entry` | First actor in the flow (receives initial message from gateway) |
| `exit` | Last actor before return (reports completion to gateway) |
| `entryexit` | Single-actor flow: both entry and exit |
| `router` | Generated router (control flow, conditions, mutations) |
| `actor` | Regular actor without special role |

One actor can logically have multiple roles, but `asya.sh/flow-role`
is a single-valued K8s label. `entry` takes precedence: if an actor
is both entry and exit, use `entryexit`. The label value must be
implemented in the XRD.

### Entrypoint and exitpoint detection

The compiler detects entry and exit points automatically:

- **Entrypoint**: the first user actor called in the flow. If the flow
  starts with `p = await handler_a(p)`, then `handler_a` IS the entry
  point — no separate start router generated. Always exactly one
  entrypoint per flow.

- **Exitpoint**: the last actor before each `return`. A flow with
  multiple return statements (e.g., in branches) has multiple exit
  points. No separate end router generated if the last actor can
  serve as exit.

This eliminates empty start/end routers (aint `20c9`).

### Flow composition (inline expansion)

A flow can call another flow. The compiler inlines the inner flow's
body at compile time:

```python
@flow
async def outer(p):
    p = await step_a(p)
    p = await inner_flow(p)   # another @flow function
    p = await step_b(p)
    return p
```

The compiler expands `inner_flow`'s body inline. All actors get
`asya.sh/flow=outer` (the outermost flow's label). The inner flow's
actors appear in a `group` in graph.json for visual clustering in the
UI. No additional `asya.sh/*` labels are added for inner flows.

Multiple levels of nesting produce nested groups. Each reference to
the same inner flow creates new actor instances — actors are not
shared across flow references.

### Yield analysis override (mixed flow + actor routing)

When the graph shows edges from flow-declared routing AND from yield
analysis of user-written handlers, **yield analysis wins**. The graph
shows actual runtime routing, not declared intent.

Example: flow declares `handler_b → handler_c`, but handler_b's code
contains `yield "SET", ".route.next", ["x-pause"]`:

```python
# In handler_b.py (user-written)
async def handler_b(p):
    if p["needs_review"]:
        yield "SET", ".route.next", ["x-pause"]
        yield p
    else:
        yield p  # continues normal flow routing
```

Graph shows:
- `handler_b → x-pause` (label: `p['needs_review']`, override: true)
- `handler_b → handler_c` (label: `else`)

The flow-declared edge `handler_b → handler_c` is kept only for the
`else` branch. The `override: true` flag in graph.json marks
yield-derived edges that replace flow-declared routing.

### asya serve integration

`asya serve` is a consumer of the compiler, not part of it.
Integration surface:

```
asya serve ──reads──→ .asya/config.yaml
           ──calls──→ compile("flow.py") → FlowInfo (in memory)
           ──serves──→ FlowInfo to UI via REST (from memory)
           ──dumps──→ files to disk (for persistence/CLI access)
           ──writes──→ common/ overlays (when user edits actor config in UI)
           ──watches──→ .py files (recompile on change, file watching)
```

Memory-first, files for durability: `asya serve` stores `FlowInfo` in
memory and serves the UI from that. Files are written as a durable
cache. No data race between reading and writing compiled artifacts.

File-watching applies to `.py` files. Jupyter notebook cells require
explicit re-run of `compile()`. VSCode extension watches on file save.

## Proposed Architecture

### Architecture decision: Path A (Yield-Analysis-First)

The compiler uses yield analysis as the unified mechanism for graph
topology extraction. Source of truth = deployment artifacts (code +
manifests), not an intermediate representation.

**Rationale**: (1) Single mechanism for both flow-generated routers and
user-written handlers. (2) Source of truth is what's actually deployed.
(3) No IR boundary tension — actors ARE the representation. (4) Yield
analysis is needed for user handlers (scenario E) regardless; using it
for generated routers too is free.

### Module structure

```
src/asya-lab/asya_lab/flow/
├── __init__.py          # exports: @flow, compile(), FlowInfo
├── compiler.py          # orchestrator: parse → codegen → manifests → analyze → graph (~150 lines)
├── parser.py            # AST → list[Operation] (~500 lines, was 718)
├── codegen.py           # list[Operation] → routers.py (~350 lines, was 636)
├── analyzer.py          # routers.py + handlers → GraphData (~200 lines, NEW)
├── graphgen.py          # GraphData → DOT + MMD + graph.json (~150 lines, was 782 dotgen)
├── rules.py             # compiler rules, extended with treat_as: routing (~60 lines, was 55)
├── errors.py            # exceptions (retained)
│
│ DELETED:
├── ir.py                # GONE (12 types → operation types in parser.py)
├── grouper.py           # GONE (715 lines → 0)
└── dotgen.py            # GONE (782 lines → 0, replaced by graphgen.py)
```

**Estimated totals**: ~1410 lines (from ~3206, -56%). Deleted: ir.py (88) +
grouper.py (715) + dotgen.py (782) = 1585 lines removed.

**TODO**: Integrate with `AsyaProject` for config-driven paths (output dirs,
image mapping, Python interpreter) instead of hard-coding.

### Compiler pipeline

```
flow.py ──→ [1. Parse] ──→ [2. CodeGen] ──→ [3. Manifests] ──→ [4. Analyze] ──→ [5. GraphGen] ──→ FlowInfo
```

```python
class FlowCompiler:
    def compile(self, source_file: Path) -> FlowInfo:
        # 1. Parse
        result = self.parser.parse(source, filename)

        # 2. Generate code
        code = self.codegen.generate(result)
        write(compiled_dir / "routers.py", code)

        # 3. Generate manifests
        manifests = self.templater.generate(result)
        write(manifests_dir / "base/", manifests)

        # 4. Analyze (yield analysis + manifest error edges)
        graph = analyzer.analyze(
            routers_file=compiled_dir / "routers.py",
            handler_files=resolve_handlers(result.actors),
            manifest_dir=manifests_dir / "base/",
        )

        # 5. Generate graph outputs
        write(compiled_dir / "graph.json", graphgen.to_json(graph))
        write(compiled_dir / "flow.dot", graphgen.to_dot(graph))
        write(compiled_dir / "flow.mmd", graphgen.to_mermaid(graph))

        return FlowInfo(...)
```

Steps 1-3 are **per-flow** (transform Python syntax to yield ABI code +
manifests). Step 4 includes **cross-handler yield analysis** across all
handlers referenced by the flow. Step 5 renders the graph in multiple formats.

### parser.py — AST → operations

The parser uses Python's `ast` module to parse the `@flow` function body
and produces a flat list of operations. It uses the project's Python
interpreter (via `--python` or auto-detected) to resolve imports, decorators,
and handler metadata.

#### Operation types

```python
@dataclass
class ActorCall:
    name: str           # handler function name (FQN)
    lineno: int
    source_file: str    # resolved source file path

@dataclass
class Mutation:
    code: str           # raw Python code
    lineno: int

@dataclass
class Conditional:
    test: str                          # Python expression
    true_branch: list[Operation]
    false_branch: list[Operation]
    lineno: int

@dataclass
class Loop:
    test: str | None                   # None = while True (no built-in guard)
    body: list[Operation]
    lineno: int

@dataclass
class FanOut:
    target_key: str
    pattern: str                       # "comprehension" | "literal" | "gather"
    actor_calls: list[tuple[str, str]]
    iter_var: str | None
    iterable: str | None
    lineno: int

Operation = ActorCall | Mutation | Conditional | Loop | FanOut
```

**Note on Loop**: `while True` loops have `test: None`. There is NO
built-in `max_iterations` guard — loop termination is the user's
responsibility in handler code.

#### Unmatched Python constructs

Try/except, with-blocks, and decorators that do NOT match any compiler
rule still exist in user flow code. The parser handles these as follows:

| Construct | With matched rule | Without matched rule |
|---|---|---|
| `try/except` | Extract error types → `resiliency_rules` in `ParseResult`. Sidecar handles MRO matching via aint `7179` policies. | Compile error with guidance: "Add a compiler rule or restructure as actor-level error handling" |
| `with ctx_mgr():` | `treat_as: config` → extract to manifest. `treat_as: inline` → wrap body as Mutation. | Compile error: "Unknown context manager. Add a compiler rule." |
| `@decorator` | `treat_as: config` → extract args to manifest + add to `ASYA_IGNORE_DECORATORS`. | Compile error: "Unknown decorator. Add a compiler rule." |

This is a **strict** approach: the compiler rejects constructs it doesn't
understand rather than silently ignoring them. Users must either add a
compiler rule or restructure the code.

#### ParseResult

```python
@dataclass
class ParseResult:
    flow_name: str
    operations: list[Operation]
    actors: list[ActorRef]          # resolved handler metadata
    resiliency_rules: list[dict]    # from try/except → manifest resiliency.rules
    extracted_configs: list[dict]   # from decorator/context manager extraction
    ignore_decorators: list[str]    # FQNs for ASYA_IGNORE_DECORATORS env var
    imports: list[str]
    constants: list[str]
```

#### Where eliminated IR types went

| Eliminated type | Where it went |
|---|---|
| Break | Codegen emits `yield "SET", ".route.next", [resolve(convergence)]` |
| Continue | Codegen emits `yield "SET", ".route.next", [resolve(self)]` (skip to loop top) |
| Return | Codegen emits routing to exit actor |
| Raise | Manifest config — sidecar routes to error handler |
| TryExcept | Parser extracts error types → `resiliency_rules` in ParseResult (aint `7179`) |
| ExceptHandler | Same — folded into `resiliency_rules` |
| WithBlock | `treat_as: config` → manifest. `treat_as: inline` → Mutation wrapping the code |

**Important**: `yield "SET", ".route.next", []` means **abort this payload**
(send directly to x-sink), NOT break. Break routes to the convergence point
after the loop; abort routes to x-sink for terminal failure.

### codegen.py — operations → Python code

```python
class CodeGenerator:
    def generate(self, result: ParseResult) -> str:
        """Generate routers.py source code from parsed operations."""
        ...
```

CodeGen walks the operations list and generates router functions directly.
No Router dataclass. No grouper. The code generator produces Python:

- `ActorCall` → `_next.append(resolve("handler_name"))`
- `Mutation` → raw code string inserted
- `Conditional` → `if test: ... else: ...` with routing in branches
- `Loop` → self-referencing router (condition check + body routing)
- `FanOut` → multi-yield pattern (same as today)

Each control flow point becomes a router function. Sequential actors
between control flow points are grouped into a single router.

### analyzer.py — yield analysis

The analyzer uses Python's `ast.parse()` to statically analyze handler
files and extract routing edges from yield statements. It handles three
categories of handlers uniformly:

```python
def analyze(
    routers_file: Path,
    handler_files: list[Path],
    manifest_dir: Path | None = None,
) -> GraphData:
    """Yield analysis: read handler code, extract routing edges."""
    ...

@dataclass
class GraphData:
    nodes: list[dict]   # {"id", "flow_role", "label", "sources"}
    edges: list[dict]   # {"from", "to", "label", "type", "override"}
    groups: list[dict]  # {"id", "nodes"}
```

#### Three handler categories

1. **Generated routers** (`routers.py`): Full yield analysis — all
   patterns analyzable since the compiler generated them.
2. **User-written handlers** (project source): Best-effort yield
   analysis via `inspect.getsource()` or direct file read. Captures
   `yield "SET", ".route.next"` patterns for override edges.
3. **External package handlers** (site-packages): Best-effort via
   `inspect.getsource()`. Opaque node if source unavailable
   (C extensions, bytecode-only).

#### Algorithm

1. **Parse generated routers** → extract `route.next` lists → build
   routing chains
2. **Parse user handlers** via `ast.parse(inspect.getsource(handler))`
   → extract override edges (yield SET patterns)
3. **Parse manifests** → `resiliency.rules[*].thenRoute` → error
   routing edges (dashed lines in graph)
4. **Merge**: chains + overrides + error edges. Override edges from
   user handlers replace flow-declared edges (marked `override: true`).

#### Analyzable yield patterns

| Pattern | Edge type |
|---|---|
| `yield "SET", ".route.next", ["actor_a", "actor_b"]` | Explicit edge(s) to named actors |
| `yield "SET", ".route.next[:0]", [resolve("x")]` | Prepend edge to resolved handler |
| `yield "SET", ".route.next", []` | Abort — terminal node (route to x-sink) |
| `yield payload` / `yield p` | Implicit edge (pass-through to route.next) |
| `yield "FLY", {...}` | No routing edge (ephemeral upstream) |

#### Condition extraction

When a yield appears inside an `if/else` block, the analyzer captures
the condition as an edge label:

```python
if p['type'] == 'A':
    yield "SET", ".route.next", [resolve("handler_type_a")]
else:
    yield "SET", ".route.next", [resolve("handler_type_b")]
```

Produces edges:
- `router → handler_type_a` with label `p['type'] == 'A'`
- `router → handler_type_b` with label `else`

Complex conditions (`if complex_condition(payload)`) are kept as-is
in the label — the graph is informational, not executable.

#### Unresolvable patterns (skipped)

```python
next_actor = resolve(payload["type"])  # runtime-computed
yield "SET", ".route.next", [next_actor]
```

Dynamic routing where the target is a variable (not a string literal
or `resolve("literal")` call) produces no edge in the graph. The
node is marked with `unresolved_routing: true`.

Future: compiler rules with `treat_as: routing` and `maps_to` field
can teach the analyzer how to resolve custom routing functions (extends
aint `1fmi`).

#### Edge cases

| Case | Handling |
|---|---|
| Multi-yield handlers (fan-out actors) | Forbidden in flows. Standalone actors: each yield = one outgoing edge. |
| Multiple `yield "SET", ".route.next"` | Last one wins (or all shown as conditional branches if inside if/else). |
| External C extensions | Opaque node, no internal edges. |
| `yield "SET", ".route.next", []` | Abort — marks node as terminal, edge to x-sink. |

### graphgen.py — GraphData → output formats

Three simple renderers consuming the same `GraphData`:

```python
def to_dot(data: GraphData, flow_name: str) -> str: ...
def to_mermaid(data: GraphData, flow_name: str) -> str: ...
def to_json(data: GraphData, flow_name: str) -> dict: ...
```

Each renderer is ~50 lines (node iteration + edge iteration +
formatting). Total ~150 lines replacing 782-line dotgen.py.

## User Workflow Catalog

### W1: New flow (script/package)

```
DS writes flow.py with @flow and handler imports
→ asya compile flow.py
→ routers.py + manifests/ + graph.json + flow.svg generated
→ DS views graph (SVG or in asya serve UI)
→ DS clicks actor nodes in UI to customize config
→ customizations write to common/ overlay
→ deploy via kustomize
```

### W2: Edit flow (iterate)

```
DS edits flow.py (add/remove actor call, change condition)
→ asya compile flow.py
→ base/ regenerated, common/ overlay preserved
→ graph.json and SVG regenerated reflecting changes
```

### W3: Edit handler (iterate)

```
DS edits handler_a.py (change business logic or yield pattern)
→ asya compile flow.py (full recompile)
→ yield analysis re-runs on handler_a.py
→ graph.json updated with handler_a's actual routing
```

### W4: Notebook development

```
DS writes @flow function in cell
→ result = compile("flows/my_flow.py")
→ SVG(result.svg) renders inline / FlowWidget(result.graph) for interactive
→ DS iterates: edit cell, re-run compile, view updated graph
→ asya serve handles deployment via REST API
```

### W5: Flow composition (inline expansion)

```
DS writes flow_a calling flow_b
→ asya compile flow_a.py
→ compiler inlines flow_b's body
→ all actors get asya.sh/flow=flow-a
→ graph shows flow_b's actors in a visual group
→ separate manifests per actor, all in flow-a's base/ directory
```

### W6: Actor config customization

```
DS compiles flow → views graph in asya serve UI
→ clicks actor node → side panel shows XRD-based config editor
→ edits replicas, resources, timeout, retry policy
→ changes write to common/ kustomize overlay
→ recompile doesn't overwrite common/
```

### W7: Multi-team monorepo

```
team1/.asya/config.yaml overrides repo root/.asya/config.yaml
→ DS runs asya compile from team1/ directory
→ nearest .asya/config.yaml wins (team1 overrides)
→ repo-level config provides base defaults
→ team-level config overrides image mapping, output paths
```

### W8: Mixed flow + actor routing (scenario E)

```
Flow declares: handler_a → handler_b → handler_c
handler_b internally does yield "SET", ".route.next", ["x-pause"] on condition
→ asya compile flow.py
→ yield analysis detects handler_b overwrites routing
→ graph shows: handler_b → x-pause (conditional, override:true)
                handler_b → handler_c (else branch)
→ flow-declared edge handler_b → handler_c replaced for that branch
```

## Edge Cases

### Single-actor flow

```python
@flow
async def simple(p):
    p = await classify(p)
    return p
```

`classify` is both entrypoint and exitpoint: `flow_role: entryexit`.
No router generated. No `is_generated` actors. Manifest has label
`asya.sh/flow-role: entryexit`.

### Multiple exitpoints

```python
@flow
async def branching(p):
    if p["urgent"]:
        p = await fast_handler(p)
        return p           # exitpoint 1
    p = await slow_handler(p)
    p = await postprocess(p)
    return p               # exitpoint 2
```

Both `fast_handler` and `postprocess` are exitpoints. In graph.json,
both have `"flow_role": "exit"`. The entrypoint is whichever actor
the flow calls first (before the if/else — may be a router).

### External package handler

```python
from external_ml import classify  # pip-installed package

@flow
async def pipeline(p):
    p = await classify(p)
    return p
```

If `external_ml` source is available in site-packages, yield analysis
inspects it (best-effort). If source is unavailable (C extension,
bytecode-only), `classify` appears as an opaque node with no internal
routing edges.

### Handler with stripped decorators

```python
@retry(max_attempts=3)  # treat-as: config
async def handler_a(p):
    ...
```

Compiler extracts `max_attempts: 3` → manifest's
`spec.resiliency.retry.maxRetries`. Adds
`ASYA_IGNORE_DECORATORS=tenacity.retry` env var to manifest.
Runtime strips `@retry` at load time. Original `handler_a.py`
is never modified.

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

### Phase 4: Manifest generation and config extraction

Add manifest output to the compiler. The compiler already extracts config
via `treat-as: config` rules (`extracted_configs`). Extend this to
produce AsyncActor XR YAML alongside `routers.py`. Add
`ASYA_IGNORE_DECORATORS` env var support. Each actor in the flow gets
a manifest with handler reference, labels, extracted configuration, and
decorator stripping instructions.

### Phase 5: Unified CLI and graph.json

Replace `asya flow compile` with `asya compile`. Produce graph.json
alongside routers.py. Support multiple output formats (DOT, Mermaid, SVG).
Wire into `asya serve` REST API.

## Relationship to existing work

- **aint `1fmi` (rules engine)**: The rules engine teaches the compiler
  about custom function semantics. In the new architecture, rules inform
  both the compiler (how to extract config, what decorators to strip)
  and the yield analyzer (how to resolve dynamic routing targets).

- **aint `20c9` (empty start/end routers)**: Addressed by smart
  entrypoint/exitpoint detection. First user actor becomes entrypoint,
  last actors before return become exitpoints.

- **aint `w1br` (@flow and @unfold)**: Flow composition (inline expansion)
  replaces the need for a separate `@unfold` marker. Calling a `@flow`
  function from another `@flow` automatically triggers inlining.

- **aint `e4u9` (Phase 6: asya serve + UI)**: The graph.json schema and
  FlowInfo interface are the contract between compiler and UI. `asya serve`
  consumes FlowInfo, serves it via REST.

- **XRD changes needed**: `asya.sh/flow-role` label vocabulary
  (`entry`/`exit`/`entryexit`/`router`/`actor`) needs XRD-level
  validation support.

## What disappears

| Current component | Status |
|---|---|
| `ir.py` (12 node types) | Eliminated. No IR. Actors are the representation. |
| `grouper.py` (~715 lines) | Eliminated. Compiler emits code directly. |
| `dotgen.py` (~780 lines) | Replaced by yield-analysis DOT/Mermaid generator |
| `Router` dataclass (15+ fields) | Eliminated. No intermediate Router representation. |
| Convergence labels | Eliminated. Direct routing in generated code. |
| Try counter / loop counter / fanout counter | Eliminated. Naming embedded in codegen. |
| `asya flow compile` subcommand | Replaced by `asya compile` (top-level). |
| `asya flow graph` subcommand | Eliminated. Graph produced as part of compile. |
| Separate graph generation step | Eliminated. Graph.json always produced by compile. |

## What stays

| Component | Status |
|---|---|
| `parser.py` | Retained but simplified. Emits code more directly. |
| `codegen.py` | Retained but simplified. Fewer specialized methods. |
| `rules.py` | Retained and extended. Informs both compilation and analysis. |
| `compiler.py` | Retained. Orchestrates the pipeline. |
| `templater.py` | Retained and extended. ActorInfo gains new fields. |
| Generated `routers.py` format | Unchanged. Same yield ABI patterns. |
| `resolve()` function in generated code | Unchanged. |

## Open questions

1. **Handler path resolution in containers**: How does the compiler
   compute the in-container handler path from the local dev path?
   This depends on the image's PYTHONPATH, which may differ from
   the local dev environment.

2. **Scope of yield analysis**: How much Python should the yield
   analyzer understand? Just top-level yields? Yields inside if/else?
   Yields inside nested functions? Recommendation: if/else yields
   (for condition labels) but not deeper nesting.

3. **Anywidget reactive recompilation**: How should notebook cells
   trigger reactive recompilation without explicit `compile()` calls?
   Requires separate investigation (IPython hooks vs. anywidget
   traitlet sync vs. kernel extension).

4. **XRD label validation**: The `asya.sh/flow-role` vocabulary
   (`entry`/`exit`/`entryexit`/`router`/`actor`) needs to be
   implemented in the XRD's CEL validation rules.

5. **graph.json stability**: Should graph.json have a version field
   for forward compatibility as the schema evolves?
