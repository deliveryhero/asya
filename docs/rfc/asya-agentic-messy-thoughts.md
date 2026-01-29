## Agentic Framework Comparison Summary

### Quick Reference: Framework Landscape

**Enterprise/Production Frameworks:**
- **Google ADK** - engineering-first, built-in eval, Dev UI, native multi-agent, tool rewrite required
- **LangGraph** - mature, keeps existing LangChain tools, SQLite persistence, verbose but flexible
- **Anthropic Agent SDK** - simple API, good for quick prototypes, Anthropic-only
- **OpenAI Agents** - low learning curve, 100+ LLM support, good handoffs
- **AWS Strands SDK** - similar to ADK, tools work as normal functions + SDK DSL

**Data Science / Iterative:**
- **DSPy** - declarative, optimizer-driven, metrics-as-objectives, self-improving prompts
  - If ADK is engineering-first, DSPy is DS-first ⚠️ Good to support both!
  - Separates: Signature (behavior), Predictor (strategy), Adapter (formatting), Metrics (objectives)

**Feature-Rich:**
- **CrewAI** - role-based agents, SOPs, many LLMs, but costlier (3-5x calls), young ecosystem
- **Agno** - similar to ADK interface, needs pre/post agent hooks for asya adoption
- **HuggingFace smolagents** - lightweight, can run local transformer models

**Workflow/Visual:**
- **Bee-AI** - good simple interface, middlewares, merged into A2A (2025-08)
- **Rivet** - drag-and-drop GUI
- **Vellum** - GUI tool for workflows, observability

### Asya's Positioning

**Multi-agent problem statement (per Vladimir discussion):**
- 1 agent alone: asya not needed
- 2-3 agents with 10 tools, resilience, state, error recovery: **asya needed**
- Key issue: state transfer across agents, not just via payload
- Functional paradigm approach: syntactically call regular functions, internally send messages (Erlang-like)

**Asya Design Choices:**
- State model: `payload` = `state` (dict), `request` = `task`
- Short-term state: within task execution
- Long-term state: persisted in DB, production info for retraining
- Future: agents auto-creating sub-agents (deferred—safety/cost/reliability risks)

**A2A Protocol Integration:**
- Aligns with A2A standards: `{message_id, context_id, task_id, role, parts[]}`
- Human-in-the-loop: `input_required` state (see RFC asya-bi8)
- Event routing: dual-channel (control via SQS, streaming via HTTP)
- Custom agent support: yield pattern for event propagation

### Key Evaluation Insights

**ADK vs DSPy Philosophy:**
- **ADK (Validation-Centric):** pass/fail regression testing, ground truth matching, CI/CD pipelines
- **DSPy (Optimization-Centric):** evaluation as objective function, auto-optimize prompts/examples, scale-friendly
- **Trajectory Matching:** ADK compares action sequences (`tool_trajectory_avg_score`), DSPy checks info quality + assertions

**Tool Reusability:**
- ADK: tools must be rewritten (@Tool vs @tool)
- LangGraph: keeps all LangChain tools unchanged ✅
- Strands: important design—tools work as normal functions + SDK DSL (asya lesson?)

**State & Persistence:**
- ADK: in-memory or Vertex, prefixed keys (none, user, app, temp)
- LangGraph: SQLite, Postgres, Redis support
- Key: always update state via event tracking, not direct modification

---
## Framework Selection for RFC Planning

For **Asya's agentic layer**, consider:
1. **Learn from ADK:** evaluation patterns, state management prefixes, human-in-the-loop
2. **Adopt DSPy concepts:** if supporting DS-first users, metrics as objectives
3. **Strands' tool design:** tools must work as normal functions (syntactic benefit for multi-world)
4. **Bee-AI's middlewares:** interceptor pattern for observability
5. **GCP patterns:** multi-agent structural & functional patterns map to A2A task routing
