---
title: "Phase 2: Manifests, error handling, rules, and CLI"
status: merged
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - pr:339
dependencies:
  - dlad8
---


## Overview

Wire the new pipeline modules (from Phase 1) into a complete end-to-end
compiler: orchestrator, FlowInfo/ActorInfo interfaces, manifest generation,
entrypoint detection, and unified `asya compile` CLI command.

After this phase: `asya compile flow.py` produces routers.py + manifests/ +
graph.json + DOT + Mermaid + SVG.

## What to implement

### 1. compiler.py — 5-step pipeline orchestrator

Rewrite compiler.py to implement:

```python
class FlowCompiler:
    def __init__(self, project: AsyaProject): ...

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

### 2. AsyaProject integration

FlowCompiler receives AsyaProject instance. All paths from config:

| Compiler need | AsyaProject API | Config key |
|---|---|---|
| Compiled code output dir | `project.resolve_path("compiler.routers")` | `compiler.routers` |
| Manifest output dir | `project.resolve_path("compiler.manifests")` | `compiler.manifests` |
| Handler → image mapping | `project.resolve_image(handler_name)` | `build[].module/image` |
| Template vars | `project.build_template_context()` | `templates.*` |
| Deployment contexts | `project.get_contexts()` | `contexts.*` |
| Compiler rules | `project.cfg.compiler.rules` | `compiler.rules` |

CLI creates `AsyaProject.from_dir(source_file.parent)`. SDK receives from caller.

### 3. FlowInfo + ActorInfo interfaces

```python
@dataclass
class FlowInfo:  # renamed from CompileResult
    flow_name: str              # "my-flow" (kebab-case)
    routers_path: Path
    manifests_dir: Path
    graph: dict                 # same as graph.json content
    dot: str
    mermaid: str
    svg: str | None             # None if plot=False
    actors: list[ActorInfo]
    warnings: list[str]

@dataclass
class ActorInfo:  # extends existing templater.ActorInfo
    name: str                   # "handler-a" (K8s name)
    handler: str                # "handler_a.classify" (in-container path)
    image: str
    flow_role: str              # "start" | "end" 
    env: list[dict]
    is_generated: bool          # renamed from is_router
    manifest_path: Path
    # Local-only (not in graph.json):
    source_file: str
    source_line: int
    handler_local: str          # local dev path
```

### 4. Smart entrypoint/exitpoint detection

- Entrypoint: first user actor called in flow (no empty start router)
- Exitpoints: last actors before each `return` (no empty end router)
- `asya.sh/role` label vocabulary: `start`, `end`
- `asya.sh/generated`: boolean "true"
- Single-valued `asya.sh/role` K8s label.
- Subsumes aint `20c9`

### 5. Manifest generation

- Generate AsyncActor XR YAML into kustomize `base/` layer
- Extract decorator config via `treat_as: config` rules → manifest fields
- Add `ASYA_IGNORE_DECORATORS` env var (comma-separated FQNs) to manifest
- Scaffold `common/` overlay once, never overwrite on recompile
- Each manifest includes: handler ref, `asya.sh/flow` label, `asya.sh/flow-role` label
- `base/` is compiler-owned (always overwritable), `common/` is user-owned

### 6. Unified CLI: `asya compile`

Replace `asya flow compile` with top-level `asya compile`:

```bash
asya compile flow.py                    # everything
asya compile flow.py --no-plot          # skip SVG/DOT/MMD, graph.json still produced
asya compile flows/                     # all @flow files in directory
asya compile flow.py --python /path     # override interpreter
asya compile flow.py --flow my-flow     # override inferred flow name
asya compile flow.py --dry-run          # preview
```

Flow name inferred from `@flow def my_flow` → `my-flow` (kebab-case).
Print `export ASYA_LAB_FLOW=my-flow` hint to stdout.

Full recompile always (idempotent). No `--force` flag.

### 7. SDK compile() function

```python
from asya_lab import compile, FlowInfo

result: FlowInfo = compile("flow.py")
result = compile("flow.py", config=".asya/config.yaml", flow_name="my-flow", plot=True)
result = compile(my_pipeline)  # from function object (future)
```

SDK mirrors CLI exactly. Same pipeline, same outputs.

## Key files

- `src/asya-lab/asya_lab/flow/compiler.py` (rewrite)
- `src/asya-lab/asya_lab/flow/__init__.py` (exports: @flow, compile, FlowInfo)
- `src/asya-lab/asya_lab/compiler/templater.py` (extend ActorInfo)
- `src/asya-lab/asya_lab/compile_cli.py` (new `asya compile`)
- `src/asya-lab/asya_lab/flow_cli.py` (update/deprecate `asya flow compile`)
- `src/asya-lab/asya_lab/config/project.py` (existing AsyaProject, no changes expected)

## Absorbed tasks

### [3dp2] Compiler error handling (try/except → retryRules)

Replace 4-router try/except pattern (try_enter, try_exit, except_dispatch, reraise)
with N except_routers (one per except clause) + manifest retryRules.

- Each except clause → one except_router that overwrites route.next with handler + finally + continuation
- Actor manifests get `resiliency.policies` + `resiliency.retryRules` stamped by compiler
- Sidecar dispatches to except_router via retryRules (no Python-level type dispatch)
- `finally` actors: appended to success route naturally + included in all except_router routes
- `raise` in except body → route to `["x-sink"]`
- bare `except:` → `policies.default.thenRoute`
- No `_on_error` header side-channel

See full design in `open.3dp2.compiler-error-handling.md`.
Dependency: [7179] policy-based error handling (already merged).

### [ch0h] Adapter generation from decorated handler call sites

Auto-generate dict→dict adapter wrappers for decorated handlers (e.g., @tool
from Claude Agent SDK). Call-site driven inference for adapter shape.

### [ia37] Per-scope semantics for context managers and decorators

Change config extraction from per-actor to per-scope. E.g., `asyncio.timeout(30)`
should apply to the entire pipeline segment, not each actor individually.

### [jy9i] WhereNode extensions for policies+rules XR fields

Add `value:` (literal constants) and `append-to:` (list append) to WhereNode
for rules extraction. Needed for resiliency schema (policies+rules).

## References

- RFC: `.aint/aints/compiler-simplify/rfc.md` (sections: Compiler pipeline, AsyaProject integration, CLI interface, SDK interface, flow_role vocabulary, Config extraction)
- Design decisions: `.aint/aints/compiler-simplify/design-decisions.md`
- Error handling design: `.aint/aints/compiler-simplify/open.3dp2.compiler-error-handling.md`


## Notes:

Don't forget to uncomment `.pre-commit-hooks/compile-flows.sh` to compile flows once syntax is implemented:
```
   # Flows requiring unsupported syntax (try/except, inline with)
    [[ "$flow_name" == try_except_* ]] && continue
    [[ "$flow_name" == with_inline_ctx ]] && continue
    [[ "$flow_name" == adk_llm_auditor ]] && continue
    [[ "$flow_name" == guardrails_sandwich ]] && continue
```
