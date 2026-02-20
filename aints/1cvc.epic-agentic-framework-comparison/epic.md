---
title: "Epic: Agentic Framework Comparison"
status: open
priority: 1 # high
type: epic
---

Compare implementation of agentic patterns across frameworks (ADK, LangGraph, OpenAI Agents, CrewAI, Anthropic SDK, DSPy). Goal: understand patterns, answer RFC open questions, prepare for Asya implementation.

Patterns to implement (Phase 1):
- 01-single-agent: Baseline single agent with tools
- 02-sequential: Agent handoff chain
- 03-parallel: Fan-out/fan-in
- 04-loop: Iterative refinement with exit
- 05-human-in-loop: Pause/resume with human input

Features to compare:
- State/memory passing
- Streaming events
- Error handling
- Durability/checkpoints
- Tool signatures

Reference: docs/comparisons/agentic_frameworks/README.md


---
_Migrated from beads `asya-6wv`_
