---
description: "Comparison: Asya vs Erlang/OTP, Akka, Orleans, Dapr — actor model implementations"
---

# Actor Frameworks

**Erlang/OTP, Akka/Pekko, Microsoft Orleans, Dapr**

## TL;DR

Classical actor frameworks (Erlang/OTP, Akka/Pekko, Orleans, Dapr) give each
actor an identity, a mailbox, and a supervision tree. 🎭 Asya strips all of that
away: actors are stateless `dict -> dict` functions with no mailbox, no
references, and no supervision hierarchy. A Go sidecar handles queue I/O,
retries, and routing. The envelope carries the route, not the actor.

## Comparison Table

| Dimension | 🎭 | Erlang/OTP | Akka / Pekko | Orleans | Dapr |
|---|---|---|---|---|---|
| **Execution model** | Stateless handler behind a sidecar; envelope carries route | Lightweight processes with mailboxes on BEAM VM | Actor objects with typed mailboxes on JVM | Virtual actors (grains) auto-activated by runtime | Virtual actors over HTTP/gRPC sidecar |
| **Scaling** | Per-actor KEDA autoscaling on queue depth | Pre-fork process pools; manual clustering | Cluster sharding across JVM nodes | Silo cluster with grain placement | K8s HPA or KEDA; app-level partitioning |
| **Scale to zero** | 🟢 Native (KEDA 0-N) | 🔴 BEAM VM must run | 🔴 JVM must run | 🔴 Silo must run | 🔴 App must run (sidecar always present) |
| **Failure isolation** | Per-actor: crashed pod affects only its queue | Per-process: supervisor restarts child | Per-actor: supervision strategy restarts children | Per-grain: runtime deactivates and reactivates | Per-app: sidecar restarts; no actor-level supervision |
| **SDK lock-in** | 🟢 None -- plain Python function | 🔴 Erlang or Elixir only | 🔴 Scala / Java (Pekko: same) | 🔴 C#, F#, Java (community) | 🟢 Any language via HTTP/gRPC sidecar API |
| **Polyglot** | 🟢 Any language behind sidecar | 🔴 BEAM only | 🔴 JVM only | 🟡 Primarily .NET | 🟢 Any language via HTTP/gRPC |
| **Conceptual simplicity** | One abstraction: actor (function + YAML) | Processes, supervisors, applications, gen_servers | Actors, behaviors, supervision trees, dispatchers, routers | Grains, silos, streams, reminders, timers | Actors, state stores, pub/sub, bindings, workflows |
| **State management** | Stateless; state travels in envelope. Optional state-proxy sidecar for virtual persistent state | Per-process heap; ETS/Mnesia for shared state | Actor encapsulates mutable state; persistence via event sourcing | Grain state persisted to storage provider | Actor state persisted to configured state store |
| **Transport** | SQS, RabbitMQ, GCP Pub/Sub (pluggable) | BEAM distribution protocol | Artery (TCP/UDP) within Akka cluster | Orleans silo-to-silo protocol | HTTP/gRPC between sidecar and app; pub/sub for messaging |
| **K8s native** | ✅ CRD, Helm, Crossplane, GitOps | ❌ VM-level clustering | ❌ JVM clustering (Akka Cluster) | ❌ Silo clustering (K8s hosting possible) | ⚠️ Runs on K8s; no CRDs for actors |
| **Handler UX** | `def f(state: dict) -> dict` | `handle_call/3`, `handle_cast/2` | `Receive` partial function or typed `onMessage` | `Task<T>` async methods on grain class | HTTP/gRPC endpoint in any language |
| **Supervision model** | None -- sidecar retries; queue redelivers on crash | Hierarchical supervisor trees (one-for-one, one-for-all) | Hierarchical supervision strategies | Runtime manages grain lifecycle (activation/deactivation) | No built-in supervision; relies on K8s restarts |

## Key Differences

### No mailbox, no actor references

In classical actor frameworks, you send a message **to a specific actor** using
its reference (PID, ActorRef, grain ID). The actor has a mailbox that queues
incoming messages. In Asya, there are no actor references. The envelope's
`route.next` names a **queue**, not an actor instance. Any replica consuming
from that queue can handle the message.

```python
# Erlang -- send to a specific process
Pid ! {process, Data}.

# Akka -- send to a specific actor reference
actorRef.tell(new Process(data), getSelf());

# Orleans -- call a specific grain by ID
var grain = client.GetGrain<IProcessor>(grainId);
await grain.Process(data);
```

```python
# Asya -- no reference, no mailbox, just a function
def process(state: dict) -> dict:
    state["result"] = do_work(state["input"])
    return state
```

The sidecar pulls from a queue, calls the handler, and pushes the result to the
next queue. The handler never knows which queue, which replica, or which pod it
runs on.

### No supervision trees

Erlang and Akka use hierarchical supervision trees where a parent actor decides
what happens when a child crashes (restart, stop, escalate). Asya has no
supervision hierarchy. Failure handling is mechanical:

1. **Handler throws** -- sidecar applies the resiliency policy (retry with
   backoff, or route to `x-sink` with `phase: failed`)
2. **Pod dies mid-processing** -- message visibility timeout expires, queue
   redelivers to another replica
3. **All replicas down** -- messages accumulate in the queue; KEDA scales up new
   pods

No supervisor code to write. No restart strategies to configure. The queue is
the supervisor.

### No state inside the actor

Classical actors encapsulate mutable state. An Akka actor's `var balance = 0`
lives in JVM heap. An Orleans grain's state is persisted to a storage provider.
Asya actors are stateless -- all state travels in the envelope payload. This
means:

- Pods are fungible: any replica handles any message
- Scaling is trivial: add replicas without state partitioning
- Recovery is automatic: no state to rebuild after a crash

For actors that need persistent state (counters, caches, conversation history),
the optional `asya-state-proxy` sidecar provides virtual filesystem state
(`/state/...`) backed by S3, Redis, or NATS KV -- without making the actor a
StatefulSet.

### Infrastructure in YAML, logic in Python

In Akka, retry policies, timeouts, dispatchers, and mailbox types are configured
in application code or HOCON. In Orleans, grain storage providers and activation
policies are set in silo configuration code. In Asya, all infrastructure
concerns live in the `AsyncActor` CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: infer
spec:
  image: my-pipeline:latest
  handler: handlers.infer
  scaling:
    minReplicaCount: 0      # scale to zero when idle
    maxReplicaCount: 10
  resiliency:
    actorTimeout: 300s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
```

The Python handler remains a plain function with no framework imports.

## When to Use What

**Choose Erlang/OTP when** you need soft real-time, millions of lightweight
concurrent processes, and you are building a telecom, messaging, or database
system. The BEAM VM is unmatched for fault-tolerant, low-latency, long-lived
stateful processes.

**Choose Akka/Pekko when** you need high-throughput event processing on the JVM
with sophisticated clustering, persistence, and stream processing. Strong fit
for financial systems, event sourcing, and CQRS architectures.

**Choose Orleans when** you need virtual actors with transparent lifecycle
management in the .NET ecosystem. Ideal for game backends, IoT device twins,
and systems where millions of logical entities each hold a small amount of
state.

**Choose Dapr when** you want a polyglot sidecar pattern for general
microservice development with actor, pub/sub, and state management capabilities
across languages and cloud providers.

**Choose 🎭 Asya when** you are running AI/ML workloads on Kubernetes and need
independent per-actor scaling (especially GPU scale-to-zero), zero SDK lock-in,
dynamic routing, and agentic capabilities (A2A, MCP, pause/resume). Asya trades
the rich actor primitives of classical frameworks for operational simplicity:
your handler is a plain function, your infra is a CRD, and the queue handles
failure recovery.
