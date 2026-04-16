---
description: "Index of core concepts: actor mesh, routing, virtual actors, flow compiler, transports, storage, observability"
---

# Core Concepts

Asya 🎭 rests on a small set of ideas. Each page below explains one
capability — what it enables, why it matters, and where to go for details.

## Core Architecture

| Concept | One-liner |
|---------|-----------|
| [Actor Mesh](actor-mesh.md) | Choreography over orchestration — actors scale and fail independently |
| [Message Knows the Way](message-knows-the-way.md) | Routing lives in the envelope, not in a central coordinator |
| [Virtual Actors](virtual-actors.md) | Stateless Deployments with optional persistent memory via state proxy |

## Developer Model

| Concept | One-liner |
|---------|-----------|
| [Separation of Concerns](separation-of-concerns.md) | Data scientists write Python; platform teams configure infrastructure |
| [Dynamic Routing](dynamic-routing.md) | Actors rewrite the route at runtime — branches, loops, human-in-the-loop |
| [Flow Compiler](flow-compiler.md) | Familiar Python control flow compiled to flat actor graphs |

## Infrastructure

| Concept | One-liner |
|---------|-----------|
| [Kubernetes Native](kubernetes-native.md) | AsyncActor is a CRD — kubectl, Helm, GitOps, RBAC all work |
| [Scale Zero to Infinity](scale-to-zero.md) | KEDA watches queues — GPU pods cost nothing between batches |
| [Pluggable Transport](pluggable-transport.md) | Swap SQS, RabbitMQ, or Pub/Sub via Crossplane without changing user code |
| [Pluggable Storage](pluggable-storage.md) | S3, GCS, Redis, NATS KV — state proxy connectors for virtual actor memory |
| [Built-in Resiliency](built-in-resiliency.md) | Durable queues, retries, DLQ, SLA deadlines, timeouts |

## Integration

| Concept | One-liner |
|---------|-----------|
| [HTTP Gateway](http-gateway.md) | Bridges async actors with synchronous HTTP, A2A, and MCP |
| [Agentic Native](agentic-native.md) | Agent swarms as distributed actors with streaming and pause/resume |

## Operations

| Concept | One-liner |
|---------|-----------|
| [Built-in Observability](observability.md) | OpenTelemetry tracing, Prometheus metrics, structured logging |
| [Developer Experience](developer-experience.md) | Fits any dev flow — GitOps, any OCI image, CI/CD, local testing |
