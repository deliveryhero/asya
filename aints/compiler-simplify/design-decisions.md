# Design Decisions

Decisions made during brainstorming for the compiler simplification RFC.
Each entry records the decision and the reasoning behind it.

## Architecture

| # | Decision | Rationale |
|---|---|---|
| A1 | **Flows are sugar** — no Flow CRD. AsyncActor is the first-class citizen. Flows instantiate AsyncActors labeled `asya.sh/flow=<name>`. | Flows are ephemeral composition — actors are the deployment unit. |
| A2 | **Yields are the source of truth** — graph topology from static analysis of yield ABI events in handler code. | Unified mechanism for flow-generated routers and user-written handlers. |
| A3 | **No IR** — actors (handler code + manifests) are the representation. Graph is a transient dict, not a first-class data structure. | If actors map 1:1 to what an IR would contain, the IR is redundant. |
| A4 | **Graph is informational** — complex conditions shown as edge labels. Unresolvable dynamic routing omitted. | Users will understand `if complex_condition(payload)`. Graph doesn't need to be executable. |
| A5 | **Actor config, not graph structure** — error handling, retry, timeout are actor-level configuration, not control flow nodes. | Try/except reduces to `on_error` config, not 4 router types. |
| A6 | **Python-native resolution** — compiler uses project's Python interpreter to resolve imports, decorators, packages. Not purely syntactical. | Enables inspecting pip-installed packages, resolving cross-module imports, reading decorator args. |
| A7 | **Actor identity = resolved handler + infra config** — handler:actor is 1:N. One `foo_bar()` can produce `foo-bar`, `foo-bar-heavy`, `foo-bar-staging`. | Same handler code, different deployment configurations. |
| A8 | **Separation of concerns** — handlers/flows = DS-owned business logic (Python), manifests = platform-owned infra (kustomize base/common). | Clear ownership boundary between DS and platform teams. |

## User Workflow

| # | Decision | Rationale |
|---|---|---|
| W1 | **Flow is always required** — no standalone actor visualization. Even single actors need a flow wrapper. | Ensures every actor has `asya.sh/flow` label, can be exposed to gateway, appears in graph. |
| W2 | **Yield analysis overrides flow routes** — graph shows actual runtime routing, not declared intent. | If handler_b overwrites `route.next`, the flow-declared edge is dead. Show reality. |
| W3 | **Full recompile always** — idempotent, never overwrites kustomize `common/` overlays. | Simple, predictable. No stale state. `base/` is compiler-owned, `common/` is user-owned. |
| W4 | **1:N via graph UI** — DS clicks actor nodes to customize name/config, writes to kustomize overlay. | Interactive workflow: graph is editable, not just visualization. |
| W5 | **Config schema from AsyncActor XRD** — actor edit UI reads OpenAPI schema from XRD. | Single source of truth for editable fields. UI doesn't guess. |
| W6 | **Flow composition = compile-time inlining** — inner flow expanded, visual grouping in graph, all actors get outer flow's label. | No runtime nesting. Each flow reference creates new actor instances. Multiple nesting levels = nested groups. |
| W7 | **Smart start detection** — generated `start_*` router is `flow_role: start`. Exit detection removed (x-sink handles completion). | Eliminates no-op end routers (aint `20c9`). |
| W8 | **External handlers = best-effort** — yield analysis if source available in site-packages, opaque node otherwise. | Pragmatic: most packages have source. C extensions / bytecode-only get opaque box. |
| W9 | **Three environments: script/package, notebook, IDE** — all use the same compiler. | Batch (CLI), explicit (notebook `compile()` call), reactive (VSCode extension on save). |
| W10 | **Notebook = explicit recompile** — DS re-runs `compile()` cell. VSCode extension is reactive (on save). Anywidget for reactive notebooks is future investigation. | Simplest model for now. Reactive notebooks need separate research. |
| W11 | **Multi-team monorepo** — nearest `.asya/config.yaml` wins, repo-level as base, team-level as override. | Config resolution walks up from target file. |

## CLI / SDK Interface

| # | Decision | Rationale |
|---|---|---|
| C1 | **Single unified command: `asya compile flow.py`** — produces everything (routers.py + manifests + graph.json + DOT + MMD + SVG). | One command, one mental model. DS never forgets to regenerate the graph. |
| C2 | **File paths as arguments** (not flow names or module paths). | Tab-completable, unambiguous, no discovery needed. |
| C3 | **Flow name inferred from `@flow def my_flow(p)`** → `my-flow` (kebab-case). Override with `--flow`. | Consistent naming: Python underscore → K8s dash. Printed to stdout with `export ASYA_LAB_FLOW=my-flow` hint. |
| C4 | **No `--force` flag** — `base/` and `compiled/` are compiler-owned, always overwritable. `common/` is user-owned, only scaffolded once. | Output dirs are compiler's territory. No git status checks for compiler-owned files. |
| C5 | **SDK mirrors CLI exactly** — `compile()` → `FlowInfo` with same pipeline, same outputs. | CLI writes files + prints. SDK writes files + returns `FlowInfo` object. |
| C6 | **`CompileResult` renamed to `FlowInfo`** — symmetrical naming with `ActorInfo`. | Consistent naming: `FlowInfo` for flow, `ActorInfo` for actor. |
| C7 | **`--no-plot` skips SVG/DOT/MMD rendering** but graph.json is always produced. | UI needs graph.json. Rendering is optional but on by default. |
| C8 | **Multiple output formats**: DOT, Mermaid, SVG all generated by default. | Mermaid renders in GitHub PRs, VS Code. DOT for Graphviz tooling. SVG for quick viewing. |

## Graph and Visualization

| # | Decision | Rationale |
|---|---|---|
| G1 | **graph.json = minimal topology + source links** — deployment-level only, no local dev info. | Local paths (source_file, handler_local) stay in `FlowInfo`/`ActorInfo` only. graph.json stays clean. |
| G2 | **Node/edge labels are graph-theoretical** — `nodes[*].label` and `edges[*].label`, no semantic interpretation. | Pure graph data. `asya serve` and CLI merge with source files for rich display. |
| G3 | **`flow_role` vocabulary: `start`, `router`, `actor`** — used in both graph.json and `asya.sh/flow-role` K8s label. `start` aligns with `start_*` router naming. No exit label (x-sink handles completion). | Unified vocabulary across graph, manifests, and K8s labels. Needs XRD-level validation. |
| G4 | **`override: true` on edges** — marks yield-analyzed routing that overwrites flow-declared routing. | Distinguishes "flow said B→C" from "handler B actually routes to D" in scenario E. |
| G5 | **graph.json includes image info per node** — handler path depends on image's PYTHONPATH. | In-container handler path may differ from local dev path. Image determines resolution. |
| G6 | **graph.json includes manifest paths** — links to base/ manifest files per node. | `asya serve` and CLI can navigate from graph node to its manifest for config editing. |
| G7 | **`is_router` renamed to `is_generated`** in ActorInfo. | More accurate: generated routers vs. user-written handlers. |
| G8 | **Groups for inline flow expansion** — inner flows appear as groups in graph.json for visual clustering. | Nested inline flows produce nested groups. No extra K8s labels for inner flows. |

## Config Extraction and Decorator Stripping

| # | Decision | Rationale |
|---|---|---|
| D1 | **Compiler never modifies handler source code** — extracts config to manifest, records stripping instructions. | Handler files are DS-owned. Compiler touches only compiler-owned output. |
| D2 | **`ASYA_IGNORE_DECORATORS` env var** — comma-separated list of FQN decorators for runtime to strip at load time. | Runtime reads this env var and ignores matching decorators. E.g., `tenacity.retry,asyncio.timeout`. |
| D3 | **`treat-as: config` rules** extract decorator args → manifest fields AND add FQN to `ASYA_IGNORE_DECORATORS`. | Single rule does both: move config to XR manifest + tell runtime to ignore the decorator. |

## asya serve Integration

| # | Decision | Rationale |
|---|---|---|
| S1 | **Memory-first, files for durability** — `asya serve` stores `FlowInfo` in memory, serves UI from memory, dumps to files for persistence. | No data race between reading and writing compiled artifacts. |
| S2 | **`asya serve` is a consumer of the compiler, not part of it** — calls `compile()` → gets `FlowInfo`. | Clean boundary: compiler exposes SDK, serve handles watching/REST/websockets/UI. |
| S3 | **File-watching for .py files, explicit for notebooks** — `asya serve` watches handler/flow files. Notebook cells need explicit `compile()` re-run. | File watching is reliable for scripts. Notebook reactivity needs separate investigation. |
| S4 | **Actor config edits via UI write to kustomize `common/` overlay** — never touch `base/`. | Recompile regenerates `base/`, user customizations in `common/` survive. |

## Compiler Pipeline

| # | Decision | Rationale |
|---|---|---|
| P1 | **Five-step pipeline: Parse → CodeGen → Manifests → Analyze → GraphGen** — no grouper, no IR tree. | Parse extracts operations, CodeGen produces routers.py, Manifests produces XR YAML, Analyze does yield analysis, GraphGen renders DOT/MMD/JSON. |
| P2 | **Yield analysis runs after code + manifest generation (Step 4)** — cross-handler analysis across generated routers + user-written actors + manifest error edges. | Yield analysis needs all handler files and manifests written first. Runs on the combined set. |
| P3 | **Manifests produced by compiler (not analyzer)** — compiler knows actor config from parsing decorators/context managers. | Analyzer only knows routing topology from yields. Config extraction is a parser concern. |
| P4 | **Exactly one `start` per flow** — generated `start_*` router receives initial message from gateway. No exit label needed (x-sink handles completion). | 3-value vocabulary: `start`/`router`/`actor`. |
| P5 | **Path A: Yield-Analysis-First** — graph topology from yield analysis of deployment artifacts (code + manifests), not from an IR. | Source of truth = what's deployed. No IR boundary tension. Yield analysis needed for user handlers anyway. |
| P6 | **5 operation types: ActorCall, Mutation, Conditional, Loop, FanOut** — down from 12 IR node types. | Break/Continue → codegen routing. Return → exit routing. TryExcept → manifest resiliency.rules. WithBlock → config/Mutation via rules. |
| P7 | **Strict parser: reject unrecognized constructs** — try/except, with-block, decorators without matched compiler rules produce compile errors. | Better to fail loudly than silently ignore. Users add rules or restructure. |
| P8 | **No built-in loop guard (max_iterations)** — loop termination is user code responsibility. | Compiler should not inject hidden guards. User writes `if count > N: break` explicitly. |
| P9 | **`yield "SET", ".route.next", []` = abort (x-sink)** — empty route means terminal failure, not break. | Break routes to convergence point. Abort routes to x-sink. Different semantics. |
| P10 | **Analyzer uses `ast.parse()` on Python files** — reads pure Python code, extracts yield patterns via AST. | No custom parser needed. Python AST is the standard tool for static analysis. |
| P11 | **Three handler categories in analyzer** — generated routers (full analysis), user handlers (best-effort via inspect), external packages (opaque if no source). | Unified mechanism, graceful degradation for unavailable source. |
| P12 | **Deleted modules: ir.py, grouper.py, dotgen.py** — total 1585 lines removed. Replaced by analyzer.py (~200) + graphgen.py (~150). | Net reduction ~56% (3206 → ~1410 lines). |
| P13 | **One decision per router (invariant)** — each generated router function has at most one level of if/else. Nested control flow → chain of routers, not nested blocks. | Keeps yield analyzer trivial — flat condition extraction only. Same pattern as current compiler (see `if_nested/flow.mmd`). |

## User Workflow Catalog

| ID | Scenario | Flow |
|---|---|---|
| W1 | New flow (script) | DS writes flow.py → `asya compile` → views graph → clicks actors to configure → deploy |
| W2 | Edit flow (iterate) | DS edits flow.py → `asya compile` → base/ regenerated, common/ preserved |
| W3 | Edit handler (iterate) | DS edits handler.py → `asya compile flow.py` → full recompile, yields re-analyzed |
| W4 | Notebook development | DS edits cell → `compile()` → SVG/FlowWidget inline → iterate |
| W5 | Flow composition | DS calls flow_b from flow_a → compiler inlines → flat graph with visual groups |
| W6 | Actor config customization | DS views graph in UI → clicks node → edits config → overlay written |
| W7 | Multi-team monorepo | team1/.asya/config.yaml overrides root → nearest config wins |
| W8 | Mixed flow + actor routing | Handler overwrites route.next → yield analysis detects → graph shows override edges |
