# Virtual Actors

Asya actors are stateless Kubernetes Deployments by design. They carry no
persistent memory between invocations — all state travels in the envelope. This
keeps actors simple, horizontally scalable, and easy to replace.

Some workloads, however, need persistent memory: conversation history, tool
state, accumulated context. The **state proxy** sidecar provides this without
sacrificing the stateless deployment model.

## How it works

The state proxy is an optional sidecar container injected alongside the actor's
runtime. It exposes a virtual filesystem at `/state/...` inside the actor pod.

1. The actor handler reads or writes files under `/state/` using standard Python
   file I/O
2. The runtime intercepts these operations and forwards them to the state proxy
   over a Unix socket
3. The proxy translates file operations to the configured storage backend

The actor code looks like ordinary file I/O — no SDK, no client library, no
connection management.

## Pluggable backends

| Backend | Use case |
|---------|----------|
| S3 | Durable, cost-effective, cross-region |
| GCS | GCP-native equivalent |
| Redis | Low-latency, ephemeral or persistent |
| NATS KV | Lightweight, mesh-native |

Each backend supports configurable consistency guarantees:

- **LWW** (Last-Writer-Wins) — eventual consistency, highest throughput
- **CAS** (Compare-And-Swap) — strong consistency, conflict detection

## This is an extension, not a requirement

Most actors do not need persistent state. The state proxy is purely additive —
actors without it continue to work as simple `dict -> dict` functions. Enable it
only when an actor genuinely needs memory across invocations.

## Why not StatefulSets?

StatefulSets tie pods to specific persistent volumes and stable network
identities. This complicates scaling, upgrades, and failure recovery. Virtual
actors keep the simplicity of Deployments while gaining persistent state through
an external proxy.

## Further reading

- [State Proxy component reference](../reference/components/core-state-proxy.md)
  — configuration, architecture, backend details
- [State Proxy usage guide](../usage/guide-state-proxy.md) — how to enable and
  use state in your actors
- [State Proxy setup guide](../setup/guide-state-proxy.md) — backend
  provisioning and Helm configuration
