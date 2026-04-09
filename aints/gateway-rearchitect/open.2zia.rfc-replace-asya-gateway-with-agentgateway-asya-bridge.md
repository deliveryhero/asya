---
title: "RFC: Replace asya-gateway with agentgateway + asya-bridge architecture"
priority: 1 # high
status: open
tags: [architecture, rfc]
---

# RFC: agentgateway + asya-bridge

## Problem

`asya-gateway` (~7,150 LOC Go) is a monolith that handles MCP server, A2A server,
auth (JWT/OAuth 2.1), task state (PostgreSQL), SSE streaming, queue dispatch, mesh
sidecar callbacks, and observability. The api/mesh split requires `pg_notify` for
cross-process sync, which is risky (8KB limit, dedicated PG connection, feedback
loops, 2s poll fallback).

## Proposal

Replace `asya-gateway` with two components:

1. **agentgateway** (LF project, Rust) -- MCP server, A2A proxy, auth, rate
   limiting, guardrails, observability, admin UI. Stateless.
2. **asya-bridge** (new, Go, ~1,500-2,000 LOC) -- stateless HTTP-to-MQ translator.
   Creates envelopes, publishes to actor queues, subscribes to status/FLY subjects.
   No PostgreSQL. No pg_notify.

## Key Architectural Change

Sidecars stop POSTing to `/mesh/*` HTTP endpoints. Instead, they publish status
events to transport subjects (`status.{task_id}`, `fly.{task_id}`). The bridge
subscribes to these subjects. This eliminates:
- The api/mesh gateway split
- PostgreSQL as task state store
- pg_notify for cross-process communication
- The x-sink queue consumer in the gateway

## Architecture

```
Client --> agentgateway (MCP server, A2A proxy, auth, rate limit, guardrails)
             |
       MCP tool/call, A2A passthrough
             |
       asya-bridge (stateless, ~1,500 LOC)
         - POST /dispatch: create envelope, publish to actor queue,
           subscribe to status.{id}, stream result back
         - POST /a2a/*: A2A task lifecycle via transport subjects
         - GET /stream/{id}: subscribe to fly.{id}, SSE
         - GET /tasks/{id}: read from state-proxy (S3/GCS/Redis)
             |
       Transport (NATS JetStream preferred)
         - actor input queues (work distribution)
         - status.{task_id} (task state events, retained)
         - fly.{task_id} (FLY token streams, ephemeral)
         - resume.{task_id} (pause/resume signals)
             |
       Actor Mesh (sidecars publish to subjects, not HTTP)
```

## What agentgateway Provides (Free)

- MCP tool federation (aggregate tools from multiple meshes + external MCP servers)
- Per-tool RBAC via CEL expressions
- Token-bucket + global rate limiting
- Content guardrails (regex, OpenAI moderation, Bedrock, Model Armor)
- OpenAPI-to-MCP auto-conversion
- Built-in admin UI + MCP playground
- Full OTLP observability (Jaeger, Langfuse integration)
- MCP auth spec compliance (OIDC, Keycloak, Auth0 adapters)

## What Gets Deleted vs Created

| Component | LOC | Fate |
|---|---|---|
| asya-gateway (entire) | ~7,150 | Deleted |
| internal/envelopestore/ (PG) | ~1,593 | Deleted |
| internal/mcp/ (MCP server) | ~1,868 | Deleted (agentgateway) |
| internal/oauth/ | ~521 | Deleted (agentgateway) |
| internal/toolstore/ | ~515 | Deleted (agentgateway) |
| internal/consumer/ | ~196 | Deleted |
| **asya-bridge (new)** | 0 | **Created ~1,500-2,000 LOC** |

Net: ~70-75% code reduction.

## Transport Requirements

| Transport | Pub/Sub | Retained/Replay | KV | Fit |
|---|---|---|---|---|
| NATS+JetStream | Native | JetStream | NATS KV | Best |
| RabbitMQ | Topic exchanges | Manual | No | Good |
| Google Pub/Sub | Native | Seek | No | Good |
| SQS | Needs SNS | No | No | Weak |

## Sidecar Change (small)

```go
// Before: HTTP POST to mesh gateway
http.Post(meshGatewayURL+"/mesh/"+id+"/progress", body)
// After: publish to transport subject (same queue client)
queue.Publish("status."+id, progressMsg)
```

## A2A Without PostgreSQL

- Task state = latest retained message on status.{id} subject
- History = state-proxy (x-sink already persists there)
- Pause/resume = x-pause writes to state-proxy, publishes status; x-resume
  reads from state-proxy on resume.{id} signal
- ListTasks = prefix scan in NATS KV or state-proxy (degraded vs SQL)

## Risks

- ListTasks filtering degraded without SQL (acceptable for most AI agent use cases)
- SQS deployments need adaptation (SNS fan-out)
- agentgateway is young (~1 year, but backed by AWS/Cisco/Microsoft/Red Hat)
- NATS becomes load-bearing for state signaling, not just messaging

## Sub-tasks

- [ ] Write detailed RFC with sequence diagrams
- [ ] Prototype asya-bridge with NATS JetStream
- [ ] Prototype sidecar subject-based status publishing
- [ ] Evaluate agentgateway MCP federation with Asya flows
- [ ] Design A2A task lifecycle without PostgreSQL
- [ ] Design ListTasks with NATS KV or state-proxy
- [ ] Migration plan from current architecture
