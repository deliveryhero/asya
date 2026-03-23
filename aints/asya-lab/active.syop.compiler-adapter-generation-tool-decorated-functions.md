---
title: "Compiler: adapter generation for @tool-decorated functions"
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/asya-lab/syop.compiler-adapter-generation-tool-decorated-functions
  - branch:asya-lab/syop.compiler-adapter-generation-tool-decorated-functions
dependencies:
  - hppv
---


## Problem

The flow DSL requires all actor calls to follow `p = fn(p)` — dict in, dict out.
But real-world tools (Claude Agent SDK `@tool`, LangChain tools, custom functions)
have typed signatures like:

```python
@tool
async def get_weather(city: str, time: str) -> dict:
    ...
```

To use these in a flow today, you must manually write an adapter:

```python
@actor
def get_weather_actor(p: dict) -> dict:
    result = get_weather(p["city"], p["time"])
    p["tool_result"] = result
    return p
```

This is boilerplate that the compiler can generate automatically.

## Design

### 1. Implicit Adapter Detection (Parser)

Adapter need is detected from the AST call pattern — no config flag required.

**Trigger**: A call classified as `treat-as: actor` (via directive or rule)
where the call site is NOT the standard `p = fn(p)` pattern:

- `p["result"] = fn(p["city"], p["time"])` — subscript target, multiple args
- `p["result"] = fn(p["x"])` — subscript target, single extracted arg
- `p = fn(p["x"], p["y"])` — standard target but non-`p` args

**Detection logic**: In `_parse_assign`, when `p["key"] = fn(args)` or
`p = fn(non-p-args)` is encountered, check if `fn` has `# asya: actor`
directive or is classified as `treat-as: actor` by rules. If yes, create
`AdapterCall`. If no, remain a `Mutation`.

Async detection: if the original call site uses `await`, the adapter emits
`async def` + `await`. Otherwise plain `def`.

### 2. New IR Type: AdapterCall

```python
@dataclass
class AdapterCall:
    name: str           # function name (e.g. "get_weather")
    lineno: int
    source_file: str = ""
    input_args: list[str] = field(default_factory=list)   # ["p['city']", "p['time']"]
    output_path: str | None = None                         # "p['tool_result']" or None for p = fn(...)
    is_async: bool = False
```

Added to the `Operation` union. Codegen treats it like an `ActorCall` for
routing but also emits an adapter wrapper function.

### 3. Codegen: Separate Adapter File

Adapter code cannot go in `routers.py` (runs in generic `python:3` image).
Adapter actors need user dependencies (imports, packages).

For each `AdapterCall`, codegen emits a separate file:
`adapter_<actor_name>.py`

```python
# Auto-generated adapter for get_weather
async def adapter_get_weather(payload: dict):
    _result = await get_weather(payload["city"], payload["time"])
    payload["tool_result"] = _result
    yield payload
```

The main `routers.py` references the adapter actor by name for routing
(same as any other actor — resolved via `ASYA_HANDLER_*` env vars).

### 4. Templater: ConfigMap Mounting

The templater generates for each adapter actor:

- A ConfigMap containing the adapter code
- The actor manifest with a volume mount for this ConfigMap

This enables the "fast experimentation" workflow: users pick a base image
and mount minimal code as ConfigMap — no image build needed.

**Scope note**: The Crossplane/Helm infrastructure to actually mount
ConfigMaps into custom images may require separate infrastructure work.
This aint covers the compiler-side: detection, codegen, templater manifests.

### 5. Rules: Default Decorator Stripping

**New behavior**: All rules with `treat-as` automatically add the matched
symbol to `ignore_decorators`, so the runtime does not see it.

**Opt-out syntax**: `keep-decorator: true` — for cases where the decorator
has runtime meaning (e.g. `@lru_cache`, `@staticmethod`).

```yaml
# Stripped by default (no extra syntax needed)
- match: "tenacity.retry"
  treat-as: config
  where: [...]

# Preserved at runtime
- match: "functools.lru_cache"
  treat-as: inline
  keep-decorator: true

# @tool — stripped by default
- match: "claude_agent_sdk.tool"
  treat-as: actor
```

The `ignore_decorators` list is appended to (merged with any existing entries).

### 6. Default Rules for @tool

Added to `compiler.rules.yaml`:

```yaml
- match: "claude_agent_sdk.tool"
  treat-as: actor

- match: "langchain.tools.tool"
  treat-as: actor
```

## Components Changed

| File | Change |
|------|--------|
| `asya_lab/flow/parser.py` | `AdapterCall` type, detection in `_parse_assign` |
| `asya_lab/flow/codegen.py` | Adapter file generation, `AdapterCall` in routing |
| `asya_lab/compiler/rules.py` | `keep_decorator` field on `CompilerRule` |
| `asya_lab/flow/rules.py` | `keep_decorator` field on flow `CompilerRule` |
| `asya_lab/defaults/compiler.rules.yaml` | `@tool` rules |
| `asya_lab/compiler/templater.py` | ConfigMap + mount for adapter actors |
| `asya_lab/flow/result_types.py` | `ActorInfo` adapter metadata |

## References

- `docs/usage/guide-handler-patterns.md` — The adapter pattern
- `.aint/aints/compiler-simplify/.closed/rejected.ch0h.*` — earlier adapter design
- Claude Agent SDK tools: https://github.com/anthropics/claude-agent-sdk-python
- Aint [hppv] — config extraction infrastructure (prerequisite, merged)
