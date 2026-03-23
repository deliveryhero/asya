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

## Proposed design

Allow direct tool usage in flows with non-standard signatures:

```python
@flow
async def agent_flow(p: dict) -> dict:
    p["tool_result"] = await get_weather(p["city"], p["time"])  # asya: actor
    return p
```

The compiler:

1. **Detects** non-`p = fn(p)` call pattern (assignment to `p["key"]`, multiple
   args, or args that aren't just `p`)
2. **Infers** input paths from AST: `p["city"]`, `p["time"]`
3. **Infers** output path from AST: `p["tool_result"]`
4. **Generates** an adapter actor with the inferred mapping:

```python
# Auto-generated adapter
async def adapter_get_weather(p: dict) -> dict:
    result = await get_weather(p["city"], p["time"])
    p["tool_result"] = result
    return p
```

5. **Deploys** the adapter as a router-like actor (uses the generated code)

### Scope detection

The parser already classifies calls. For adapter generation, the trigger is:
- Assignment to `p["key"] = fn(...)` where `fn` has `# asya: actor` directive
- OR `fn` is decorated with `@tool` (matched by a config rule)
- The function takes args other than just `p`

### Config rule for @tool

```yaml
- match: "claude_agent_sdk.tool"
  treat-as: actor
  adapter: true

- match: "langchain.tools.tool"
  treat-as: actor
  adapter: true
```

The `adapter: true` flag tells the compiler to generate an adapter wrapper
instead of expecting `dict -> dict` conformance.

### IR extension

`ActorCall` gets optional fields:
- `input_paths: list[str]` — e.g. `["p['city']", "p['time']"]`
- `output_path: str` — e.g. `"p['tool_result']"`
- `adapter: bool` — whether to generate adapter code

### What the codegen emits

For each adapter actor, the codegen emits:

```python
async def adapter_get_weather(payload: dict):
    _result = await get_weather(payload["city"], payload["time"])
    payload["tool_result"] = _result
    yield payload
```

This is included in the generated `routers.py` alongside router functions.

## References

- `docs/usage/guide-handler-patterns.md` — The adapter pattern
- `.aint/aints/compiler-simplify/.closed/rejected.ch0h.*` — earlier adapter design
- Claude Agent SDK tools: https://github.com/anthropics/claude-agent-sdk-python
- Aint [hppv] — config extraction infrastructure (prerequisite, merged)
