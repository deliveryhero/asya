---
title: "Research: before/after callbacks for model and tool interceptors"
priority: 3 # low
type: task
tags:
  - type:research
---

Research how to support ADK-style before/after callbacks for LLM calls and tool
execution in the Asya actor mesh.

## ADK Pattern

ADK provides four callback types on each agent:

```python
LlmAgent(
    before_model_callback=fn,   # intercept before LLM call
    after_model_callback=fn,    # intercept after LLM response
    before_tool_callback=fn,    # intercept before tool execution
    after_tool_callback=fn,     # intercept after tool result
)
```

Each can **short-circuit** (skip the LLM/tool) or **modify** the request/response.

Use cases:
- Guardrails: reject harmful prompts before LLM call
- Cost control: cache responses, skip LLM if cached
- Logging/auditing: record all tool calls and results
- Result transformation: modify tool output before LLM sees it
- Auth injection: add credentials to tool context

See survey-adk-data-flow.md Section 4.9 for callback type signatures and
execution priority (plugin first, then agent-level, first non-None wins).

## Asya Challenges

In Asya, actors run on separate pods. There is no in-process interception point
between "before LLM call" and "LLM call" -- the LLM call happens inside the
actor handler.

### Potential Approaches

**A. Sidecar middleware (before/after message delivery)**

The sidecar could run configurable middleware before delivering a message to the
runtime and after receiving the response:

```yaml
# AsyncActor spec
middleware:
  before_handler:
    - name: guardrails
      image: my-guardrails:latest
  after_handler:
    - name: audit-log
      image: my-audit:latest
```

Each middleware is a small container or function that processes the message
envelope. This is analogous to HTTP middleware or gRPC interceptors.

**B. Router actors in the flow (pre/post processing actors)**

Insert dedicated actors before/after the LLM actor in the flow:

```python
async def guarded_llm_flow(state: dict) -> dict:
    state = await guardrails(state)    # before_model equivalent
    state = await llm_call(state)
    state = await audit_log(state)     # after_model equivalent
    return state
```

Already supported by the flow compiler. No new infrastructure needed.

**C. Handler-level callbacks (decorator pattern)**

Provide a Python decorator that wraps the handler with before/after logic:

```python
from asya_runtime import before_handler, after_handler

@before_handler(guardrails_check)
@after_handler(audit_log)
async def my_handler(state: dict) -> dict:
    ...
```

This runs within a single actor, similar to ADK's in-process model.

### Recommendation

Option B is the most Asya-native approach (actors are the unit of composition).
Option C is useful for single-actor patterns. Option A is the most powerful but
requires sidecar changes.

For full agentic support, Option B covers the use cases. The flow compiler
already generates router actors for mutations -- a "guardrail router" is the
same pattern.

## Questions to Resolve

1. Should callbacks be a first-class concept in the AsyncActor CRD, or purely
   a flow-level concern?
2. Should the sidecar support pluggable middleware, or is actor composition
   sufficient?
3. How do before/after callbacks interact with streaming (partial events)?
   In ADK, before_model runs once before streaming starts. In Asya, the
   sidecar would need to buffer or pass through.

## References

- survey-adk-data-flow.md Section 4.9 (Callbacks)
- survey-adk-data-flow.md Section 4.3 (Tool execution pipeline -- 8 steps)
- survey-agentic-frameworks.md (CrewAI event bus, LangGraph state reducers)
