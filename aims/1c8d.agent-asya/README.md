---
title: Agentic Asya
status: open
priority: 2 # medium
type: epic
---

Enable Asya framework to natively support agentic use-cases, facilitating migration from orchestrator-based frameworks (Google ADK, CrewAI, DSPy, Agno, BeeAI, Strands SDK, OpenAI Agents) to choreography-based Asya.

## Vision
Extend asya flow compile capabilities to translate agentic framework code into async actor networks. Shift from centralized orchestration (RPC mindset) to decentralized choreography (Continuation-Passing Style). Agents/tools become independent actors with identities, wallets, and communication protocols - true Decentralized AI (DeAI) stack.

## Approach
- NO pip package distribution - translate user code to async actors (avoid migration burden)
- Separate tools and agents → separate actors
- Explore better actor signatures beyond current dict-based approach (e.g., tool-style: def get_weather(city: str) -> str)
- Breaking changes acceptable (no users yet)

## Key Findings from Pre-RFC (ADK Analysis)
- Dual-channel architecture: control flow (SQS/Pub/Sub) vs. streaming events (HTTP)
- asya-gateway as central communication hub, must be compliant with:
  - ACP (A2A protocol) - agent-to-agent communication
  - A2UI protocol - user agents exposed via HTTP streaming (WebSocket/SSE)
- Events NOT propagated through parent agents (unlike ADK centralized orchestration)
- Streaming events (partial text, audio, transcriptions) sent directly from actors to gateway via HTTP
- Only state transfer/control events (function calls, agent transfers, final responses) sent between actors via message queues
- Framework-level event classification - user code just yields events, runtime classifies and routes
- Session state in message payload (with compression: artifact references, compaction, sliding window)

## Open Questions
1. State management - sessions, conversation history across actor boundaries
2. Free variables - auto-append results to payload (flatten control flow like asya flow does for if/else)
3. Actor/tool detection - framework-specific semantics vs. blind decomposition at await boundaries
4. Unsupported patterns - await handlers, try-catch, for/while loops, pydantic/TypedDict vs plain dict
5. Multi-framework support strategy

## Context
See /tmp/rfc-adk-to-asya.md for initial ADK exploration. Goal: interactive problem exploration, gradual issue creation for smaller tasks.


---
## Notes

## Session State Strategy (Concluded 2026-01-28)

**Decision: Message-truth by default with layered complexity**

### Core Strategy
1. **Message-truth by default** - session carried in envelope payload
2. **Binary protocol (TLV)** - ~2.5x effective capacity vs JSON
3. **Artifact references mandatory** - media always in S3/GCS, never inline
4. **External state ONLY for fan-out/fan-in** - scoped to aggregator actor

### Why This Works
- SQS limit is 1 MiB (not 256KB) - most conversations fit
- Binary serialization adds ~40-60% compression
- Media offloaded to object storage keeps messages small
- Only parallel execution needs coordination state

### Priorities Achieved
- ✅ Simplicity: No external session store for sequential flows
- ✅ Low latency: No DB roundtrips for most operations
- ✅ Scale: Binary protocol + 1MiB limit handles 200+ turn conversations
- ✅ Durability: Media persisted to S3/GCS, messages are self-contained

### Research Beads Created
- asya-o42: Queue size limits across transports
- asya-6j2: Binary protocol design (TLV + Marshal)
- asya-zpl: Stateful actor for fan-out/fan-in
- asya-z1o: Media storage abstraction (fsspec)


---
_Migrated from beads `asya-bi8`_
