---
title: "Epic: A2A Protocol Compliance for Gateway"
status: open
priority: 1 # high
type: epic
---

Transform asya-gateway from current /envelopes/* routes to A2A-compliant /messages and /tasks/* endpoints. This enables external agents to interact with Asya actor networks using the standard Agent2Agent protocol.

## Current State
- /envelopes/{id} - Get envelope status
- /envelopes/{id}/stream - SSE streaming  
- /envelopes/{id}/progress - Sidecar progress updates
- /envelopes/{id}/final - End actor final status
- /tools/call - REST tool invocation
- /mcp - MCP JSON-RPC endpoint
- No authentication

## Target State (A2A Compliant)
- /.well-known/a2a/agent-card - Agent discovery
- /messages - Send message (POST)
- /messages:stream - Send with streaming (POST)
- /tasks/{id} - Get task status (GET)
- /tasks - List tasks (GET)
- /tasks/{id}:subscribe - SSE subscription (GET)
- /tasks/{id}:cancel - Cancel task (POST)
- /tasks/{id}/pushNotificationConfigs - Push notification CRUD
- Authentication (Bearer, OAuth2, API Key)

## Key Terminology Changes
- envelope → task (A2A terminology)
- envelope_id → task_id
- Add context_id for conversation grouping

## References
- RFC: docs/rfc/asya-bi8-agentic-asya.md
- A2A Spec: https://a2a-protocol.org/latest/specification/
- A2A Definitions: https://a2a-protocol.org/latest/definitions/


---
## Notes

## Exploration: MCP + A2A Dual-Protocol Strategy (2026-02-05)

### Key Insight: MCP and A2A Serve Different Purposes

**Keep MCP as-is** (current implementation):
- `/mcp` - Streamable HTTP endpoint (JSON-RPC 2.0)
- `/mcp/sse` - SSE endpoint (backward compatibility)
- `/tools/call` - Simple REST interface
- `/envelopes/*` - Status, streaming, progress

**Why keep MCP:**
1. **Easy testing** - Developers can use `asya mcp call` CLI for quick tests
2. **Sync access to async actors** - MCP tools abstract away async complexity
3. **LLM integration** - MCP is the standard for LLM tool calling
4. **Fine-grained control** - Each tool maps to a specific actor route

**Add A2A on top** (new capability):
- `/.well-known/agent.json` - Agent Card discovery
- `/a2a` or `/messages` - Agent-to-Agent messaging
- `/tasks/*` - Task lifecycle (A2A terminology)

**Why add A2A:**
1. **Agent-to-Agent communication** - External AI agents can discover and use Asya
2. **Single public identity** - Asya platform appears as one "Super Agent"
3. **Intent-based routing** - Smart gateway can route by intent, not explicit actor names
4. **Industry standard** - A2A is emerging as the agent interoperability protocol

### Architecture: Gateway Pattern

Based on RFC `thoughts-a2a-gateway-pattern.md`:

```
External Agents ──► A2A (/a2a) ──┐
                                 │
Developers ──────► MCP (/mcp) ──►├──► Internal Actor Mesh
                                 │    (RabbitMQ/SQS)
REST Clients ────► /tools/call ─┘
```

**Single Gateway, Multiple Protocols:**
- A2A: "I need to process a refund" → Gateway routes to payment-processor
- MCP: `tools/call: process_refund` → Explicit tool invocation
- Both use same internal queue/actor infrastructure

### A2A Selective Exposure Strategy

**Not all actors should be A2A-exposed.** Distinction:

| Actor Type | MCP Exposed | A2A Exposed | Example |
|------------|-------------|-------------|---------|
| Public API | ✅ Yes | ✅ Yes | `generate-report`, `analyze-data` |
| Internal pipeline stage | ✅ Yes | ❌ No | `preprocessor`, `validator` |
| System actors | ❌ No | ❌ No | `happy-end`, `error-end` |

**Implementation approach:**
1. **Tool metadata** - Add `a2a_exposed: true` to tool config
2. **Agent Card generation** - Only expose A2A-enabled tools in agent.json
3. **Routing by intent** (optional) - Smart routing for natural language requests

### Proposed Endpoint Structure

```yaml
# Existing (unchanged)
/mcp                  # MCP Streamable HTTP
/mcp/sse             # MCP SSE (deprecated)
/tools/call          # REST tool invocation
/envelopes/*         # Envelope lifecycle

# New A2A endpoints
/.well-known/agent.json     # Agent Card discovery
/a2a                        # A2A JSON-RPC messaging (Gateway Pattern)
/tasks                      # A2A task listing (maps to envelopes)
/tasks/{id}                 # Task status (maps to envelope status)
/tasks/{id}:subscribe       # SSE streaming (maps to envelope stream)
```

### Agent Card Example

```json
{
  "name": "Asya Gateway",
  "description": "AI Actor Mesh for distributed workloads",
  "versions": [{
    "version": "1.0.0",
    "endpoint": "https://asya.example.com/a2a",
    "interfaces": ["rpc"]
  }],
  "skills": [
    {
      "name": "generate_report",
      "description": "Generate business analytics report"
    },
    {
      "name": "process_payment", 
      "description": "Process payment transactions"
    }
  ]
}
```

### Tool Config Extension

```yaml
tools:
  - name: generate_report
    description: "Generate business analytics report"
    a2a_exposed: true  # ← NEW: Include in Agent Card
    parameters:
      format: {type: string, options: [pdf, html, json]}
    route: [formatter, report-generator, delivery]
    
  - name: internal_validator
    description: "Internal validation step"
    a2a_exposed: false  # ← Not exposed to external agents
    route: [validator]
```

### Implementation Priority

1. **Phase 1: Agent Card** (P1)
   - `/.well-known/agent.json` endpoint
   - Generate from existing tool config (filter by a2a_exposed)

2. **Phase 2: A2A Messaging** (P1)
   - `/a2a` JSON-RPC endpoint
   - Route `invoke_actor` method to internal actors
   - Map responses to A2A format

3. **Phase 3: Task API** (P2)
   - Map existing envelope API to A2A task terminology
   - `/tasks/*` endpoints as aliases for `/envelopes/*`

4. **Phase 4: Smart Routing** (P3)
   - Intent-based routing (optional LLM-powered)
   - "I need to..." → resolve to specific actor

### Non-Goals (Deferred)

- **Multi-namespace A2A** - Initially expose single-namespace agents
- **Authentication** - Separate concern (can add OAuth2/Bearer later)
- **Push notifications** - Complex, defer to future iteration
- **gRPC transport** - Focus on HTTP first

### Relationship to Existing Beads

This exploration complements but doesn't replace existing sub-tasks:
- asya-4c1: Agent Card endpoint (Phase 1)
- asya-u76: POST /messages (maps to A2A /a2a)
- asya-2n8: GET /tasks/{id} (Phase 3)
- asya-z80: Task SSE subscription (Phase 3)

**New consideration:** Add `a2a_exposed` metadata to tool config schema.


---
_Migrated from beads `asya-7j1`_
