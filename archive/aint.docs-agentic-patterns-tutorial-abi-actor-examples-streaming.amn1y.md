---
title: "docs: agentic patterns tutorial + ABI actor examples (streaming, dynamic routing, pause/resume)"
status: merged
priority: 2
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/agentic-umbrella/amn1.docs-agentic-patterns-tutorial-abi-actor-examples-streaming
  - branch:agentic-umbrella/amn1.docs-agentic-patterns-tutorial-abi-actor-examples-streaming
  - pr:285
---

Write the missing narrative documentation and code examples for Asya's three
runtime agentic patterns — patterns that go beyond Flow DSL compilation and
require generator actors with the ABI yield protocol.

## Context

`examples/flows/agentic/` already has 15 compilable Flow DSL patterns
(ReAct loops, parallel fan-out, human-in-the-loop via approval gates, etc.).
`docs/reference/abi-protocol.md` documents the four ABI verbs (GET/SET/DEL/FLY).

What's missing is the bridge: a tutorial that explains *why* and *when* to use
generator actors, and concrete working examples for the three patterns that
Flow DSL alone cannot express.

## Deliverables

### 1. `docs/tutorials/agentic-patterns.md`

Tutorial covering the three ABI-based agentic patterns with worked examples,
mapping to ADK equivalents where helpful:

**Pattern 1 — Dynamic routing (transfer_to_agent equivalent)**
- Problem: Flow DSL compiles static conditions. LLMs decide targets at runtime.
- Solution: generator actor reads `payload["_transfer_to"]`, emits
  `yield "SET", ".route.next", [target]`
- Show both: LLM actor as generator (self-routing) vs. separate dispatcher actor
- Optional: enum validation with `ASYA_HANDLER_*` env vars to prevent hallucinated targets
- ADK parallel: `event.actions.transfer_to_agent = "BillingAgent"`

**Pattern 2 — Live streaming (token-by-token output to UI)**
- Problem: LLM generates tokens incrementally; users expect streaming responses
- Solution: generator actor yields `"FLY"` events upstream to the gateway
  (gateway forwards as SSE to the client)
- Show: streaming an Anthropic/OpenAI response token-by-token
- Note: FLY events bypass the queue; they go directly via HTTP to the gateway
- ADK parallel: `Event(partial=True, content=Part(text="..."))`

**Pattern 3 — Pause/resume for human input**
- Problem: actor needs human approval before continuing (tool confirmation,
  sensitive action gate)
- Solution: actor raises `input_required` status signal → sidecar marks task
  as `paused` → client polls gateway, provides input, resumes
- Clarify the actor-side contract: what the handler yields/returns to trigger pause
- Show: how gateway task ID links the paused task to the resume endpoint
- ADK parallel: `should_pause_invocation()` / long-running tool pattern

Each pattern section:
- Short motivation (1 paragraph)
- Complete, runnable actor code (no stubs — works out of the box with mock LLM)
- How it maps to envelope flow (ASCII diagram or numbered steps)
- Cross-reference to relevant `examples/flows/agentic/` file where applicable

### 2. New examples in `examples/actors/agentic/`

Generator actor Python files (not Flow DSL — these are directly deployable
actor handlers, not compilable flows):

- `dynamic_routing.py` — dispatcher actor using `yield "SET", ".route.next"`
  with enum validation from env vars
- `live_streaming.py` — LLM actor streaming tokens via `yield "FLY"` using
  the Anthropic API (with a mock fallback that doesn't require an API key)
- `pause_for_human.py` — actor that signals pause via `input_required` status,
  waits for resume, then continues

Each file: self-contained, has a module docstring explaining the pattern,
deployable as `ASYA_HANDLER=dynamic_routing.dispatcher`.

### 3. Update `examples/actors/agentic/README.md` (new file)

- Brief intro: "these are ABI generator handlers, not Flow DSL"
- Table listing the three examples with one-liner descriptions
- Pointer to `docs/tutorials/agentic-patterns.md` for explanation
- Pointer to `examples/flows/agentic/` for the Flow DSL patterns

## Out of Scope

- Implementing new ABI verbs or changing the runtime
- Changing the Flow DSL compiler
- Full end-to-end Kubernetes deployment yamls for each pattern
  (the tutorial shows the actor code; deployment follows standard AsyncActor YAML)

## Acceptance Criteria

- `docs/tutorials/agentic-patterns.md` exists and covers all three patterns
- `examples/actors/agentic/{dynamic_routing,live_streaming,pause_for_human}.py` exist
- `examples/actors/agentic/README.md` exists
- All Python files pass `make lint` (ruff, no mypy needed for examples)
- No broken cross-references to files that don't exist
