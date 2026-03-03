---
title: "Test: create async flow example fixtures (ADK-based)"
priority: 1 # high
type: task
---




Create example async flow .py files for testing the agentic flow compiler. All examples based on real ADK patterns.

## Files to Create

### examples/flows/async_sequential.py
Based on ADK LLM Auditor (SequentialAgent):
- async def llm_auditor(state: dict) -> dict
- state = await critic(state)
- state = await reviser(state)
- return state

### examples/flows/react_loop.py
Based on ADK LlmAgent with tools (ReAct pattern):
- async def agent_with_tools(state: dict) -> AsyncGenerator[dict, None]
- state["messages"] = state.get("messages", [])
- while True: state = await llm_call(state)
- if state.get("tool_calls"): state = await execute_tool(state)
- else: yield {"type": "result", **state}; return

### examples/flows/react_multi_tool.py
Based on ADK agents with multiple tools:
- async def research_agent(state: dict) -> AsyncGenerator[dict, None]
- while True: state = await llm_call(state)
- if tool_name == "search": state = await web_search(state)
- elif tool_name == "calculator": state = await calculator(state)
- elif tool_name == "code_exec": state = await code_executor(state)
- else: yield {"type": "result", **state}; return

### examples/flows/async_conditional.py
Based on ADK conditional agent routing:
- async def content_pipeline(state: dict) -> dict
- state = await classifier(state)
- if state["content_type"] == "text": state = await text_processor(state)
- elif state["content_type"] == "image": state = await image_processor(state)
- else: state = await generic_processor(state)
- state = await quality_check(state)

### examples/flows/async_nested.py
Nested await in conditional branches:
- async def review_pipeline(state: dict) -> dict
- state = await initial_review(state)
- if state["score"] < 0.5: state = await detailed_review(state); state = await human_review(state)
- else: state = await auto_approve(state)

## Purpose
- Serve as golden test fixtures for the compiler
- Validate parsing, CPS transformation, router generation
- Can also serve as documentation/examples for users

## References
- ADK LLM Auditor: https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor
- RFC: docs/rfc/agentic-compiler/agentic-compiler-rfc.md Section 9.2


---
**Close reason**: Implemented in PR #174 - 5 async flow fixtures + pre-commit exclusions


---
_Migrated from beads `asya-fudp`_
