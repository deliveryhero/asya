---
title: "Test: ADK LLM Auditor compilation and execution test"
status: merged
priority: 1
parent: 7b55c
tags:
  - worktree:.worktrees/1c8d/1flmd6.test-adk-llm-auditor-compilation-execution-test
  - branch:1c8d/1flmd6.test-adk-llm-auditor-compilation-execution-test
  - pr:219
---

Create comprehensive tests that compile the ADK LLM Auditor example and verify correctness.

## Test File
testing/component/flow-compiler/tests/test_adk_llm_auditor.py

## Tests

### test_parse_sequential_async
- Parse async_sequential.py (llm_auditor flow)
- Verify IR contains 2 AwaitCall nodes (critic, reviser)
- Verify flow is detected as async

### test_compile_sequential_async
- Compile async_sequential.py to routers
- Verify 3+ routers generated (entry, continuation, end)
- Verify route contains [critic, reviser] in correct order

### test_execute_sequential_async
- Execute generated router code against mock envelope
- Set ASYA_HANDLER_CRITIC=critic, ASYA_HANDLER_REVISER=reviser
- Verify route.actors is correctly populated
- Verify route.current is advanced correctly

### test_compile_react_loop
- Compile react_loop.py (ReAct pattern with while True)
- Verify loop back-edge router is generated
- Verify dispatch router has conditional branch
- Verify collect router routes back to llm_call

### test_execute_react_loop_no_tools
- Execute ReAct routers with payload that has no tool_calls
- Verify flow exits loop, routes to happy-end

### test_execute_react_loop_with_tools
- Execute ReAct routers with payload that has tool_calls
- Verify dispatch routes to tool actor
- Verify collect routes back to llm_call (loop back)

## References
- Fixtures: examples/flows/async_sequential.py, react_loop.py
- RFC Section 9.2 Test Cases 1-2


---
_Migrated from beads `asya-yfv1`_
