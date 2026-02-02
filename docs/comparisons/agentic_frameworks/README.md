# Agentic Framework Comparison

Comparative implementation of agentic design patterns across frameworks.

**Goal**: Create minimal but working implementations of each pattern in each framework to:
1. Understand implementation differences
2. Identify best practices for Asya adoption
3. Answer open questions in RFCs (asya-bi8, asya-fan-in-fan-out, asya-handler-signatures)

## Frameworks

| Framework | Priority | Notes |
|-----------|----------|-------|
| Google ADK | P1 | Primary RFC focus, engineering-first |
| LangGraph | P1 | Mature, keeps existing tools |
| CrewAI | P2 | Role-based agents, SOPs |
| Anthropic SDK | P3 | Simple API, Anthropic-only |
| DSPy | P3 | Different paradigm (DS-first) |

## Patterns (from GCP Architecture Guide)

Implementing subset most relevant to Asya's architecture:

### Phase 1: Core Patterns

| Pattern | Description | Asya Relevance |
|---------|-------------|----------------|
| 01-single-agent | One agent + tools | Baseline for comparison |
| 02-sequential | Agent A → B → C | Basic routing validation |
| 03-parallel | Fan-out → N agents → Fan-in | Core RFC topic |
| 04-loop | Iterate until exit condition | Control event separation |
| 05-human-in-loop | Suspend → human input → resume | A2A `input_required` state |

### Phase 2: Advanced Patterns (future)

| Pattern | Description |
|---------|-------------|
| 06-coordinator | Central dispatch to specialists |
| 07-review-critique | Generator + critic agents |
| 08-hierarchical | Multi-level task decomposition |

## Directory Structure

```
docs/comparisons/agentic_frameworks/
├── README.md                    # This file
├── {framework}/
│   ├── pyproject.toml          # Framework-specific dependencies
│   └── {pattern}/
│       ├── agent.py            # Implementation
│       └── README.md           # Pattern notes
```

## Progress Tracking

### Phase 1: Core Patterns

#### Pattern 01: Single Agent ✅
- [x] google-adk/01-single-agent
- [x] langgraph/01-single-agent
- [x] crewai/01-single-agent
- [x] anthropic-sdk/01-single-agent
- [x] dspy/01-single-agent

#### Pattern 02: Sequential
- [ ] google-adk/02-sequential
- [ ] langgraph/02-sequential
- [ ] crewai/02-sequential
- [ ] anthropic-sdk/02-sequential
- [ ] dspy/02-sequential

#### Pattern 03: Parallel (Fan-Out/Fan-In)
- [ ] google-adk/03-parallel
- [ ] langgraph/03-parallel
- [ ] crewai/03-parallel
- [ ] anthropic-sdk/03-parallel
- [ ] dspy/03-parallel

#### Pattern 04: Loop
- [ ] google-adk/04-loop
- [ ] langgraph/04-loop
- [ ] crewai/04-loop
- [ ] anthropic-sdk/04-loop
- [ ] dspy/04-loop

#### Pattern 05: Human-in-the-Loop
- [ ] google-adk/05-human-in-loop
- [ ] langgraph/05-human-in-loop
- [ ] crewai/05-human-in-loop
- [ ] anthropic-sdk/05-human-in-loop
- [ ] dspy/05-human-in-loop

## Features to Compare

For each implementation, document:

| Feature | Questions to Answer |
|---------|---------------------|
| **State/Memory** | How is state passed between agents? Session vs payload? |
| **Streaming** | How are partial events streamed? SSE? WebSocket? |
| **Error Handling** | How are errors propagated? Retry policies? |
| **Fan-Out/Fan-In** | Dynamic N? How are results aggregated? |
| **Durability** | Checkpoints? Persistence? Resume from failure? |
| **Human Input** | How to pause/resume? Timeout handling? |
| **Tool Signatures** | Typed vs dict? Schema extraction? |

## References

- [GCP Agentic Design Patterns](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [Asya RFC: Agentic Asya](../rfc/asya-bi8-agentic-asya.md)
- [Asya RFC: Fan-In/Fan-Out](../rfc/asya-fan-in-fan-out.md)
- [Asya RFC: Handler Signatures](../rfc/asya-handler-signatures.md)
