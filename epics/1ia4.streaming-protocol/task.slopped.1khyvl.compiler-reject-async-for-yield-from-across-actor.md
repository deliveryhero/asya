---
title: "Compiler: reject async-for / yield-from across actor boundaries"
priority: 3 # low
type: task
---

The Flow DSL compiler must detect and reject patterns that attempt to
re-yield partial events across actor boundaries:

FORBIDDEN — compiler must reject:
  async for event in agent_llm(prompt):
      yield event  # Cannot forward partials through queues

FORBIDDEN — same issue with yield-from:
  yield from agent_llm(prompt)

These patterns cannot work because partial events are transport-level
(HTTP direct from sidecar to gateway) and cannot flow through message
queues. See RFC Section 2 for the full rationale.

Implementation:
- In the flow compiler parser (src/asya-cli/), detect async-for and
  yield-from AST nodes
- Emit a clear compile-time error explaining why this is not supported
- Add unit tests for the rejection

Note: This is P3 because no user is currently writing flows with generators.
The compiler currently does not support loops at all, so async-for would
already fail. This task adds an explicit, descriptive error message.
