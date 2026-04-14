---
title: "Research: HolmesGPT for AI-assisted Asya debugging"
status: open
priority: 2
tags:
  - type:feature
---

## Research Objective

Evaluate HolmesGPT (https://github.com/HolmesGPT/holmesgpt) as an AI-assisted debugging tool for Asya actors and pipelines. Explore integration points with asya-stagedoor (MCP) and asya-gateway (A2A).

**Status:** CNCF Sandbox project

## What is HolmesGPT?

AI-powered Kubernetes troubleshooting assistant that:
- Analyzes logs, events, and metrics
- Uses LLMs to correlate symptoms with root causes
- Suggests remediation steps
- Integrates with alerting systems (PagerDuty, OpsGenie, etc.)

## Why Consider for Asya?

**Asya debugging is complex:**
- Multiple actors in a pipeline
- Async message passing (hard to trace)
- Scale-to-zero (pods may not exist when debugging)
- Queue backlogs, DLQ accumulation
- KEDA scaling decisions

**HolmesGPT could help:**
- "Why did this envelope fail?" → Analyze actor logs, queue state, error patterns
- "Why is this actor scaling unexpectedly?" → Correlate KEDA metrics with pod events
- "What's causing the latency spike?" → Trace envelope journey across actors

## Integration Points

### 1. asya-stagedoor (MCP-compliant K8s info)

**Concept:** Limited, safe MCP interface for K8s object introspection

HolmesGPT could use MCP tools to:
- `get_actor_status(name)` → Pod health, replica count, last restart
- `get_queue_depth(actor)` → Messages pending, DLQ count
- `get_actor_logs(name, lines)` → Recent logs (filtered/sanitized)
- `get_envelope_trace(id)` → Envelope journey across actors
- `get_keda_metrics(actor)` → Scaling triggers, current value

**Security considerations:**
- Read-only access
- No secrets/configmaps content
- Rate limiting
- Audit logging

### 2. asya-gateway (A2A-compliant actor API)

**Concept:** A2A (Agent-to-Agent) protocol for AI agents to interact with Asya pipelines

HolmesGPT could use A2A to:
- Trigger test envelopes to reproduce issues
- Query envelope status
- Stream actor responses for analysis
- Invoke diagnostic actors (health checks, self-tests)

**Use case:** HolmesGPT sends a test envelope, monitors its progress, identifies where it fails.

## Key Research Questions

### 1. HolmesGPT architecture

- How does it gather context? (kubectl, Prometheus, logs)
- What LLM backends supported? (OpenAI, Anthropic, local)
- How extensible is tool/data source integration?
- Can it use MCP tools directly, or need adapter?

### 2. MCP vs native integration

- Does HolmesGPT support MCP already?
- If not, what's the effort to add MCP tool support?
- Alternative: Write HolmesGPT plugin that calls asya-stagedoor

### 3. A2A protocol fit

- Is A2A the right protocol for diagnostic interactions?
- Or should HolmesGPT use MCP for everything (read + write)?
- A2A might be overkill for simple "send test envelope"

### 4. Context window considerations

- Asya pipelines can have many actors, deep logs
- How does HolmesGPT handle large context?
- Need smart summarization of actor states?

### 5. Self-hosted vs SaaS

- HolmesGPT appears self-hosted (runs in cluster)
- Good for security (no data leaves cluster)
- But adds operational burden

## Potential Architecture

```
┌─────────────────┐     MCP      ┌─────────────────┐
│   HolmesGPT     │◄────────────►│  asya-stagedoor │
│  (AI debugger)  │              │  (K8s read API) │
└────────┬────────┘              └────────┬────────┘
         │                                │
         │ A2A                            │ K8s API
         ▼                                ▼
┌─────────────────┐              ┌─────────────────┐
│  asya-gateway   │              │   K8s cluster   │
│ (envelope API)  │              │ (actors, queues)│
└─────────────────┘              └─────────────────┘
```

**Flow:**
1. Alert fires: "Actor X error rate > 5%"
2. HolmesGPT receives alert
3. Uses asya-stagedoor MCP tools to gather context
4. Optionally uses asya-gateway A2A to send test envelope
5. LLM analyzes, suggests: "Actor X OOMKilled, increase memory limit"

## Research Deliverables

1. **HolmesGPT evaluation** - Install, test with simple K8s app
2. **MCP integration spike** - Can HolmesGPT consume MCP tools?
3. **asya-stagedoor design** - What tools needed for Asya debugging?
4. **Demo** - HolmesGPT debugging a failing Asya pipeline

## Links

- HolmesGPT: https://github.com/HolmesGPT/holmesgpt
- CNCF Sandbox announcement: (find link)
- MCP spec: https://modelcontextprotocol.io/
- A2A spec: https://google.github.io/A2A/


## Notes

## Initial Thoughts (from creation)

**asya-stagedoor concept:**
- "Stagedoor" = backstage access for authorized visitors
- MCP-compliant server exposing limited K8s introspection
- NOT a full K8s API proxy (security nightmare)
- Curated set of tools for Asya-specific debugging
- Could run as sidecar to HolmesGPT or standalone service

**Tool ideas for asya-stagedoor:**
```
list_actors(namespace) → [{name, status, replicas, queue_depth}]
get_actor_details(name) → {pods, events, keda_status, recent_errors}
get_envelope_status(id) → {current_actor, history, headers}
get_queue_metrics(actor) → {depth, dlq_count, oldest_message_age}
get_actor_logs(name, since, filter) → [log_lines] (sanitized)
describe_flow(name) → {actors, routes, diagram}
```

**Why MCP for stagedoor?**
- MCP is designed for LLM tool access
- HolmesGPT (or any AI debugger) can consume MCP natively
- Standardized protocol, not another custom API
- Same tools usable by Claude, GPT, local models

**asya-gateway A2A angle:**
- Gateway already exists for envelope submission
- A2A would add agent-to-agent negotiation
- Might be overkill - simple REST/MCP might suffice
- But A2A allows: "I'm an AI agent, here's my capabilities, let's collaborate"

**Synergy with other beads:**
- asya-sut (SigNoz): HolmesGPT could query SigNoz for metrics context
- asya-dl2 (A/B routing): Debugging variant-specific issues

**When would this be valuable?**
- Post-production: "Why did pipeline fail at 3am?"
- Development: "Help me understand why my actor isn't scaling"
- Incident response: AI-assisted RCA with full context


_Migrated from beads `asya-an2`_
