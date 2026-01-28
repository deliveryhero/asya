# Agent Protocol Standards Research

Research on AI agent interoperability standards relevant to Asya Gateway adoption.

**Date**: 2026-01-28
**Context**: Agentic Asya RFC (`docs/rfc/asya-bi8-agentic-asya.md`)

---

## Protocol Stack Overview

| Protocol | Purpose | Type | Status | Priority |
|----------|---------|------|--------|----------|
| **A2A** | Agent-to-agent communication | REST + SSE | Active (Google/LF) | P1 - Implement |
| **MCP** | Agent-to-tool communication | JSON-RPC 2.0 | Active (Anthropic/AAIF) | P1 - Already implemented |
| **AG-UI** | Agent-to-user streaming | Event-based SSE | Active (CopilotKit) | P2 - Implement |
| **A2UI** | Declarative UI payloads | JSON format | Active (Google) | P3 - Consider |
| **AGNTCY** | Agent infrastructure | Multiple specs | Active (LF) | P3 - Monitor |
| **ANP** | Peer-to-peer agents | DID-based | Emerging | P4 - Watch |
| **OASF** | Agent capability schema | JSON Schema | Emerging | P4 - Watch |

---

## Primary Protocols (Implement)

### A2A (Agent2Agent Protocol)

**Source**: Google, now under Linux Foundation
**Spec**: https://google.github.io/A2A/
**Status**: Production-ready, widely adopted

**Key Features**:
- Task lifecycle management (submitted → working → input_required → completed/failed)
- Agent Cards for capability discovery (JSON at `/.well-known/agent.json`)
- SSE streaming for real-time updates
- Push notifications for async completion
- Context preservation across interactions

**Endpoints**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/.well-known/agent.json` | GET | Agent Card discovery |
| `/tasks` | POST | Create task |
| `/tasks` | GET | List tasks |
| `/tasks/{id}` | GET | Get task status |
| `/tasks/{id}` | DELETE | Cancel task |
| `/tasks/{id}:subscribe` | GET (SSE) | Stream updates |
| `/messages` | POST | Send message |
| `/messages:stream` | POST (SSE) | Streaming messages |

**ACP Note**: IBM's Agent Communication Protocol (ACP) merged into A2A in September 2025. The ACP repository was archived on August 27, 2025. No separate ACP implementation needed.

---

### MCP (Model Context Protocol)

**Source**: Anthropic, now under AAIF (Linux Foundation)
**Spec**: https://modelcontextprotocol.io/
**Status**: Production-ready, Asya already implements this

**Key Features**:
- Tool discovery and invocation
- Resource management
- Prompt templates
- JSON-RPC 2.0 transport

**Asya Implementation**: Gateway exposes MCP at `/mcp` endpoint.

---

### AG-UI (Agent-User Interaction Protocol)

**Source**: CopilotKit
**Spec**: https://docs.ag-ui.com/
**Status**: Active, gaining adoption

**Purpose**: Event-based transport protocol for streaming agent responses to frontends.

**Event Types** (17 total):

| Event | Purpose |
|-------|---------|
| `lifecycle:run_started` | Run begins |
| `lifecycle:run_finished` | Run ends |
| `lifecycle:run_error` | Run failed |
| `lifecycle:step_started` | Step begins |
| `lifecycle:step_finished` | Step ends |
| `text_message:start` | Message begins |
| `text_message:content` | Message chunk |
| `text_message:end` | Message ends |
| `tool_call:start` | Tool invocation begins |
| `tool_call:args` | Tool arguments chunk |
| `tool_call:end` | Tool invocation ends |
| `tool_call:result` | Tool result |
| `state:snapshot` | Full state snapshot |
| `state:delta` | Incremental state update |
| `custom` | Custom events |
| `raw` | Raw LLM events |
| `interrupt` | Human-in-the-loop required |

**Asya Mapping**:
- `run_started/finished` → Envelope lifecycle
- `step_started/finished` → Actor processing
- `tool_call:*` → MCP tool invocations
- `interrupt` → `input_required` state (A2A compatible)

---

## Secondary Protocols (Consider)

### A2UI (Agent-to-User Interface)

**Source**: Google
**Spec**: Part of A2A ecosystem
**Status**: Active

**Purpose**: Declarative UI format for agent-generated interfaces. JSON component trees transported via A2A or AG-UI events.

**Example**:
```json
{
  "type": "card",
  "title": "Flight Options",
  "children": [
    {"type": "text", "content": "Select your preferred flight:"},
    {"type": "button", "label": "Morning Flight", "action": "select_morning"},
    {"type": "button", "label": "Evening Flight", "action": "select_evening"}
  ]
}
```

**Use Case**: When agents need to present structured UI choices to users, not just text.

---

## Linux Foundation Initiatives

### AAIF (Agentic AI Foundation)

**Source**: Linux Foundation
**Launched**: 2025
**Website**: https://lfaidata.foundation/projects/aaif/

**Founding Members**: OpenAI, Anthropic, Google, Microsoft, AWS, Meta, IBM

**Projects Hosted**:
- **MCP** (Model Context Protocol) - Anthropic's tool protocol
- **AGENTS.md** - Standardized agent documentation format
- **goose** - Open-source AI developer agent

**Relevance**: Asya should align with AAIF standards for maximum interoperability. MCP already implemented. Consider adopting AGENTS.md format for actor documentation.

---

### AGNTCY (Agent Infrastructure)

**Source**: Cisco, now under Linux Foundation
**Website**: https://agntcy.org/
**Status**: Active development

**Components**:

| Component | Purpose | Asya Relevance |
|-----------|---------|----------------|
| **Discovery** | Agent registry and lookup | Could integrate for multi-cluster |
| **Identity** | Agent authentication/authorization | Aligns with A2A auth requirements |
| **Messaging** | Agent-to-agent communication | A2A already covers this |
| **Observability** | Distributed tracing | Could adopt for pipeline debugging |

**Recommendation**: Monitor for observability standards. The identity component may be useful for multi-tenant deployments.

---

## Emerging Protocols (Watch)

### ANP (Agent Network Protocol)

**Source**: Community-driven
**Status**: Emerging specification

**Key Features**:
- Peer-to-peer agent communication (no central server)
- DID-based identity (decentralized identifiers)
- Capability-based discovery
- End-to-end encryption

**Use Case**: Decentralized agent networks, blockchain-adjacent applications.

**Asya Relevance**: Low priority. Asya uses centralized choreography (queues), not P2P. Monitor for future federation requirements.

---

### OASF (Open Agent Schema Framework)

**Source**: Community initiative
**Status**: Draft specification

**Purpose**: JSON Schema-based format for describing agent capabilities, similar to OpenAPI for REST APIs.

**Example**:
```json
{
  "agent": {
    "name": "TextAnalyzer",
    "version": "1.0.0",
    "capabilities": [
      {
        "name": "analyze_sentiment",
        "input": {"type": "object", "properties": {"text": {"type": "string"}}},
        "output": {"type": "object", "properties": {"sentiment": {"type": "string"}}}
      }
    ]
  }
}
```

**Asya Relevance**: Could complement A2A Agent Cards. Low priority until specification matures.

---

## Implementation Priority

### P1 - Critical (Implement Now)
1. **A2A Protocol** - Core agent interoperability (Epic: `asya-7j1`)
2. **MCP** - Already implemented at `/mcp`

### P2 - High (Implement Soon)
3. **AG-UI** - Frontend streaming support (Bead: `asya-0wr`)

### P3 - Medium (Consider)
4. **A2UI** - Rich UI payloads (Bead: `asya-53w`)
5. **AGNTCY Observability** - Distributed tracing

### P4 - Low (Monitor)
6. **ANP** - Future federation
7. **OASF** - Agent schema standardization
8. **AGENTS.md** - Documentation format

---

## References

- A2A Specification: https://google.github.io/A2A/
- MCP Specification: https://modelcontextprotocol.io/
- AG-UI Documentation: https://docs.ag-ui.com/
- AAIF Foundation: https://lfaidata.foundation/projects/aaif/
- AGNTCY Project: https://agntcy.org/
- CopilotKit: https://copilotkit.ai/
