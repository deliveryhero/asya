---
title: Compiler adapter generation from decorated handler call sites
status: rejected
priority: 2
dependencies:
  - srn2x
  - 1fmik
tags:
  - integrate-into:gml9
  - absorbed-into:gml9
---

## Problem

The flow compiler currently only extracts XR spec values from decorated/configured
calls (e.g. tenacity retry params -> `spec.resiliency.*`). It cannot generate
**adapter code** that bridges a non-`dict->dict` handler to the actor protocol.

Users writing agentic flows use framework decorators like `@tool("greet", "Greet a user", {"name": str})`
(Claude Agent SDK, MCP, LangChain) where the handler signature is `(args) -> dict`,
not `(p: dict) -> dict`. Today users must write manual adapters
(see `docs/tutorials/actor-handler-adapter-pattern.md`).

## Goal

The compiler should automatically generate adapter handlers when a decorated function
is called in a flow and the decorator matches a rule requiring adapter generation.

## Design

### Call-site driven inference

The adapter shape is inferred from how the function is called in the flow, not from
hardcoded templates. The user writes natural Python; the compiler transpiles it.

```python
# Module-level: decorated handler
@tool("greet", "Greet a user", {"name": str})
async def greet_user(args):
    return {"content": [{"type": "text", "text": f"Hello, {args['name']}!"}]}

# Flow: call site defines the adapter contract
async def flow(state: dict) -> dict:
    state = await llm_actor(state)
    if "custom_tool_call" in state:
        state["custom_tool_call_result"] = greet_user(state["custom_tool_call"]["args"])  # asya: actor
    return state
```

From the call site AST the compiler extracts:

| Piece | AST node | Inferred |
|-------|----------|----------|
| Input path | `Call.args[0]` = `Subscript(Subscript(Name("state"), "custom_tool_call"), "args")` | `payload["custom_tool_call"]["args"]` |
| Output path | Assignment target = `Subscript(Name("state"), "custom_tool_call_result")` | `payload["custom_tool_call_result"]` |
| Decorator | `FunctionDef.decorator_list` -> rule match | needs adapter |
| Original sig | `FunctionDef.args` = `(args)` | single-arg, not dict->dict |

### Generated adapter

```python
# compiled/adapters/greet_user.py (mounted via ConfigMap)
from my_module import greet_user as _greet_user

async def handler(p: dict) -> dict:
    _input = p["custom_tool_call"]["args"]
    _result = await _greet_user(_input)
    p["custom_tool_call_result"] = _result
    return p
```

### Rule extension

New `adapter` field on `CompilerRule`:

```yaml
- match: "claude_agent_sdk.tool"
  treat-as: actor
  adapter: true  # signals adapter generation required
  where:
    - param: {arg: 0, kwarg: "name", type: "str"}
      assign-to: spec.metadata.tool-name
    - param: {arg: 1, kwarg: "description", type: "str"}
      assign-to: spec.metadata.description
```

### Also works with inline helper functions

The user can also write a helper that calls the tool:

```python
def get_tool(tool_call: dict) -> dict:
    if tool_call["name"] == "greet_user":
        return {
            "tool_name": "greet_user",
            "tool_call_result": greet_user(tool_call["args"]),  # asya: actor
        }
    ...
```

Same inference: the compiler sees the call site and generates the adapter. Note that the compiler
should first resolve AST into a flattened IR and only then reason about the adapter generation.

## Pipeline layering

Rules and adapter generation operate at different layers. See `docs/reference/flow-dsl.md` "Compiler
Architecture" section for the full spec. Summary:

| Concern | Layer | Why |
|---------|-------|-----|
| "Is `tool` a known decorator?" | Rules (AST) | needs pattern matching on symbol names |
| "What are its parameters?" | Extractor (AST) | needs `ast.Call` arg binding |
| "What's the input/output path?" | Parser (AST -> IR) | needs `ast.Subscript` chain analysis |
| "Does this actor need an adapter?" | IR | `input_path is not None` on `ActorCall` |
| "Generate the adapter code" | Codegen (IR -> Code) | reads IR fields, emits Python |

Rules stay at AST level. The parser flattens AST into IR and enriches it with adapter metadata.
Codegen reads IR only -- it never touches AST nodes.

### IR extension for adapter metadata

```python
@dataclass
class ActorCall(IROperation):
    name: str
    treat_as: str = "actor"
    extracted_values: dict[str, object] = field(default_factory=dict)
    # Adapter metadata (populated when decorated function needs wrapping)
    input_path: list[str] | None = None      # e.g. ["custom_tool_call", "args"]
    output_path: list[str] | None = None     # e.g. ["custom_tool_call_result"]
    is_async: bool = False
    source_module: str | None = None         # for the import in generated adapter
```

## Implementation sketch

1. **Decorator detection** (depends on [srn2]) -- parser traverses `FunctionDef.decorator_list`
2. **Module function map** -- parser builds `{func_name: FunctionDef}` for top-level functions
3. **Call-site analysis** (parser, AST -> IR) -- when an actor call targets a decorated function
   needing an adapter:
   - Extract input path from call arguments (Subscript chains) -> `ActorCall.input_path`
   - Extract output path from assignment target -> `ActorCall.output_path`
   - Detect async/sync from the FunctionDef -> `ActorCall.is_async`
4. **Adapter codegen** (codegen, IR -> Code) -- reads `ActorCall` adapter fields, generates
   `dict->dict` wrapper from inferred paths
5. **Output** -- adapters saved alongside `routers.py` in `compiled/adapters/`

## Edge cases

- **Multiple tools in one helper**: if/elif branches each define a different adapter
- **List comprehension fan-out**: `[await call_tool(t) for t in state["tool_calls"]]` -> gather pattern
- **Dynamic dispatch**: `tool_call["name"]` routing -> enumerate from if/elif or generate dynamic router
- **Schema extraction**: `{"name": str}` has `str` as `ast.Name`, not constant -> extractor needs type-ref handling
