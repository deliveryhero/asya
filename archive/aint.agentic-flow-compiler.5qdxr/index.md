---
title: Agentic Flow Compiler
status: merged
priority: 2
---

Extend the Asya flow compiler to support async functions with await split points, enabling compilation of agentic workflows (LLM + tools ReAct loops, sequential/parallel agent pipelines) into distributed stateless actor networks.

## Core Transformation: CPS (Continuation-Passing Style)

Each `await` in the user's async function becomes a message boundary between actors. The compiler splits the function at await points, generating continuation routers that carry state forward in the payload.

## Scope

### Level 1: Orchestration Compilation (extend existing)
- `async def flow(state: dict) -> dict` with `state = await actor(state)` calls
- Compiles to linear/conditional actor routes (extends current sync compiler)

### Level 2: Agent Decomposition (new)
- `async def agent(state: dict) -> AsyncGenerator[dict, None]` with ReAct loops
- `while True` + `await llm_call` + conditional tool dispatch + `yield` streaming
- Compiles to: llm-call -> dispatch-router -> [tools] -> collect-router -> (loop back)

### Level 3: Framework Translation (future, out of scope)
- Recognize ADK SequentialAgent/ParallelAgent declarations and compile

## Phases

1. **Parser Extensions**: New IR nodes, async def/await/while/yield parsing
2. **CPS Transformation**: Grouper splits at await, generates continuation/loop routers
3. **Streaming Support**: Runtime async execution, multi-frame sidecar protocol
4. **Integration**: ADK LLM Auditor reference example, ReAct loop tests

## Validated Example

Real ADK LLM Auditor (SequentialAgent with critic+reviser) compiled to stateless actor network. See docs/rfc/agentic-compiler/agentic-compiler-rfc.md for full design.

## Key Design Decisions

- **Payload mode only** (for now): All actors receive/return dict
- **Free variables**: Not supported across await boundaries (user must pass state explicitly)
- **Last yield = control event**: AsyncGenerator last yield goes to queue, intermediates go to HTTP streaming
- **No sticky sessions**: Full state travels in payload, any pod can process any message
