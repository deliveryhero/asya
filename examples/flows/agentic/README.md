# Agentic Flow Patterns

Real-world agentic AI patterns expressed as Asya Flow DSL definitions.

Each file is a compilable flow that demonstrates a distinct agentic design
pattern with stub actor handlers. The patterns are derived from analysis of:

- [Google ADK Samples](https://github.com/google/adk-samples/) (43 samples)
- [Google Cloud: Choose a design pattern for agentic AI](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [LangGraph Workflows & Agents](https://langchain-ai.github.io/langgraph/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [AutoGen Teams](https://microsoft.github.io/autogen/)

## Pattern Catalog

### Category A: Single-Agent Loops

| File | Pattern | Flow Primitives |
|------|---------|-----------------|
| `react_tool_loop.py` | ReAct (Reason + Act) | `while True` + `if/elif` tool dispatch + `break` |
| `plan_and_execute.py` | Plan, Execute, Re-Plan | sequential + `while` step loop |
| `research_and_refine.py` | Iterative Research (Search-Critique-Deepen) | `while True` + sequential critique + conditional `break` |

### Category B: Pipeline Patterns

| File | Pattern | Flow Primitives |
|------|---------|-----------------|
| `sequential_pipeline.py` | Sequential Agent Pipeline | linear chain `A -> B -> C -> D` |
| `routing_classifier.py` | Input Classification & Dispatch | `if/elif/else` on category |
| `guardrails_sandwich.py` | Safety Guardrails (Pre/Post Validation) | `try/except` wrapping core agent |
| `rag_pipeline.py` | Adaptive RAG | sequential + conditional re-query loop |

### Category C: Parallel Patterns

| File | Pattern | Flow Primitives |
|------|---------|-----------------|
| `parallel_sectioning.py` | Parallel Sectioning (Fan-Out/Fan-In) | fan-out list literal + aggregator |
| `voting_ensemble.py` | Parallel Voting / Best-of-N | fan-out same task N times + judge |
| `map_reduce.py` | Map-Reduce Over Data Partitions | splitter + comprehension fan-out + reducer |

### Category D: Multi-Agent Collaboration

| File | Pattern | Flow Primitives |
|------|---------|-----------------|
| `evaluator_optimizer.py` | Generator-Critic Refinement Loop | `while` + generate + evaluate + `break` |
| `orchestrator_workers.py` | Dynamic Orchestrator with Workers | `while True` + `if/elif` dynamic dispatch |
| `hierarchical_delegation.py` | Hierarchical Multi-Level Delegation | nested `if/elif` + sub-pipelines |
| `multi_agent_debate.py` | Multi-Agent Debate / Deliberation | fan-out + `while` rounds + fan-out revise (fan-out inside while loop) |

### Category E: Human-Agent Interaction

| File | Pattern | Flow Primitives |
|------|---------|-----------------|
| `human_in_the_loop.py` | Human Approval Checkpoints | sequential + approval gate + `if/else` |

## Summary Matrix

| # | Pattern | Structural Signature | Key ADK Sample |
|---|---------|---------------------|----------------|
| 1 | ReAct Tool Loop | `while True -> LLM -> if tool -> execute -> loop` | Customer Service, SWE Benchmark |
| 2 | Plan-and-Execute | `plan -> while steps -> execute -> replan` | Deep Search |
| 3 | Research & Refine | `while gaps -> search -> critique -> refine` | Academic Research |
| 4 | Sequential Pipeline | `A -> B -> C -> D` | Financial Advisor, Podcast Transcript |
| 5 | Routing Classifier | `classify -> branch -> merge` | Brand Search Optimization |
| 6 | Guardrails Sandwich | `try: validate -> process -> validate` | Safety Plugins, CaMeL |
| 7 | RAG Pipeline | `retrieve -> (re-query loop) -> generate` | RAG |
| 8 | Parallel Sectioning | `[A, B, C] -> aggregate` | Parallel Task Decomposition |
| 9 | Voting Ensemble | `[A, A, A] -> judge` | Story Teller |
| 10 | Map-Reduce | `split -> [same_op x N] -> reduce` | (general pattern) |
| 11 | Evaluator-Optimizer | `while quality < threshold -> generate -> evaluate` | Image Scoring, LLM Auditor |
| 12 | Orchestrator-Workers | `while incomplete -> orchestrate -> dispatch worker` | Travel Concierge, Data Science |
| 13 | Hierarchical Delegation | `root -> mid -> leaf (tree structure)` | Plumber, Data Science |
| 14 | Multi-Agent Debate | `fan-out -> while not converged -> share -> revise` | (academic: Du et al. 2023) |
| 15 | Human-in-the-Loop | `work -> gate -> if approved continue` | Deep Search, Order Processing |

## Compiling

```bash
# Compile a single flow
asya flow compile examples/flows/agentic/react_tool_loop.py -o compiled/ --plot

# Validate all flows
for f in examples/flows/agentic/*.py; do
    echo "--- $f ---"
    asya flow validate "$f"
done
```

## How flows map to Asya actors

Each flow compiles to router actors. Handler functions referenced in the flow
(e.g., `llm_call`, `retrieve_docs`) are deployed as separate AsyncActors.

```
Flow source (.py)
    |
    v
  asya flow compile
    |
    v
  routers.py          <-- deployed as router AsyncActors
  + handler stubs     <-- deployed as handler AsyncActors (user implements)
```

The mapping from handler names to actor names uses `ASYA_HANDLER_*` environment
variables on router actors. See the [Flow DSL Reference](../../../docs/reference/flow-dsl.md)
for deployment details.

### Flow composition

Since compiled flows have the same signature as actors (`dict -> dict`), a flow
can call another flow: `state = await sub_flow(state)`. The sub-flow's start
router is just another actor. This enables hierarchical composition — each team
or sub-pipeline can be its own compiled flow deployed as an independent actor
network.

## Compiler gaps found during development

These patterns exposed parser limitations, all fixed in PR #246.

| Gap | Severity | Status | Description |
|-----|----------|--------|-------------|
| Empty `[]` as fan-out | P1 | ✅ Fixed | `state["x"] = []` now correctly parsed as mutation |
| Non-call list as fan-out | P2 | ✅ Fixed | `state["x"] = [state.get("y")]` now correctly parsed as mutation |
| Fan-out inside while loops | P3 | ✅ Fixed | Verified at runtime: fan-out, break, and continue all work inside while loops |

**Not a gap** (initially thought to be):
- Dynamic fan-out: supported via list comprehension `[actor(x) for x in items]`
- Sub-flow composition: works because flows are actors (same signature)
