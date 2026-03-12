---
title: Asya vs Ray
priority: 2 # medium
---

Asya vs Ray: Execution Models

Fundamental Paradigm

┌─────────────────┬──────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────┐
│                 │                           Ray                            │                             Asya                             │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Model           │ Distributed computing framework (RPC + shared memory)    │ Actor mesh framework (message queue choreography)            │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Communication   │ Direct method calls via .remote(), shared object store   │ Envelopes over message queues (SQS, PubSub, Unix sockets)    │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Coupling        │ Tight — caller holds object refs, awaits futures         │ Loose — fire-and-forget, no caller-callee binding            │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ State           │ In-process (actor instance variables)                    │ Stateless pods + optional state-proxy sidecar (S3/GCS/Redis) │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Scheduling      │ Centralized (Ray scheduler places tasks/actors on nodes) │ Decentralized (routing embedded in each envelope)            │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Topology        │ Dynamic — tasks spawn tasks, actors call actors          │ Declarative — pipeline topology defined in CRDs or flow DSL  │
├─────────────────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────┤
│ Deployment unit │ Python process on a Ray cluster node                     │ Kubernetes pod with sidecar (Crossplane-managed)             │
└─────────────────┴──────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────┘

Actor Model Comparison

Ray actors are in-process Python objects. You call actor.method.remote(args) and get a future. State lives in instance variables. Methods on the same actor serialize; across actors they
parallelize. Actors can call each other directly — essentially RPC with distributed object refs.

Asya actors are Kubernetes Deployments with a sidecar router. They receive an envelope from a queue, process it (dict -> dict), and the sidecar routes the result to the next queue. No
actor ever holds a reference to another actor — routing is data (the route.next field in the envelope). This means:

- Ray actors are tightly coupled (caller knows callee, holds a handle)
- Asya actors are fully decoupled (only the envelope knows the topology)

What Ray Has That Asya Doesn't

┌───────────────────────────────┬────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────┐
│          Capability           │                         Ray's Approach                         │                  Asya Equivalent                  │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Distributed training          │ Ray Train — DDP, DeepSpeed, Horovod integration, gradient sync │ None — wrong abstraction layer                    │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Hyperparameter tuning         │ Ray Tune — search algorithms, early stopping, trial scheduling │ None                                              │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Data processing               │ Ray Data — streaming datasets, map/filter/batch across cluster │ None (preprocessing is user's concern)            │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ In-process shared memory      │ Distributed object store, zero-copy reads via Arrow/Plasma     │ Not applicable — actors share nothing             │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Sub-millisecond task dispatch │ Direct RPC to worker processes                                 │ Impossible — queue latency is ms-to-seconds       │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Fine-grained GPU scheduling   │ Fractional GPUs, placement groups, gang scheduling             │ Kubernetes-level only (resource requests on pods) │
├───────────────────────────────┼────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────┤
│ Reinforcement learning        │ RLlib — multi-agent envs, policy servers                       │ None                                              │
└───────────────────────────────┴────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────┘

What Asya Has That Ray Doesn't

┌──────────────────────────────────┬────────────────────────────────────────────────────────────┬───────────────────────────────────────────────┐
│            Capability            │                      Asya's Approach                       │                Ray Equivalent                 │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ K8s-native declarative deploy    │ AsyncActor CRD → Crossplane renders pod + sidecar + queues │ Manual — you provision infra yourself         │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Transport abstraction            │ Swap SQS/PubSub/NATS/Unix socket without code changes      │ Hardcoded to Ray's internal transport         │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Envelope-based routing           │ Route is data — dynamic re-routing via yield "SET"         │ Hardwired in code (caller calls callee)       │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Built-in DLQ / error handling    │ x-sump auto-routes failed envelopes to dead-letter         │ Manual error handling per actor               │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Pause/resume (human-in-the-loop) │ x-pause checkpoints to S3, x-resume re-injects             │ Not built-in                                  │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Protocol compliance              │ A2A + MCP gateway out of the box                           │ Ray Serve is HTTP only                        │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Flow DSL → actor pipeline        │ Python control flow compiles to CPS message chains         │ No equivalent (you wire actors manually)      │
├──────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ Queue-level autoscaling          │ KEDA scales pods by queue depth                            │ Ray autoscaler is cluster-level, not per-task │
└──────────────────────────────────┴────────────────────────────────────────────────────────────┴───────────────────────────────────────────────┘

Where They Overlap (and Diverge)

Model serving: Ray Serve deploys models as HTTP endpoints with replica scaling, batching, and model composition. Asya's gateway exposes actor pipelines as MCP tools or A2A agents. Both
serve models over HTTP, but Ray Serve is optimized for low-latency inference with in-process model loading, while Asya is optimized for async pipelines where latency tolerance is higher.

Pipeline composition: Ray lets you chain tasks/actors with output = step2.remote(step1.remote(input)) — synchronous DAG style. Asya defines pipelines as route.next = ["actor_a",
"actor_b"] — asynchronous chain style. Ray's approach is more flexible (arbitrary DAGs, branching on futures). Asya's approach is more resilient (every hop is persisted to a queue,
survives pod crashes).

Scaling: Ray scales at the cluster level (add nodes, autoscaler reacts to pending tasks). Asya scales at the actor level (KEDA watches queue depth, scales individual Deployments
independently). Asya's model is more Kubernetes-idiomatic; Ray's is more like a single distributed runtime.

Summary

Ray = a distributed Python runtime that makes a cluster feel like one big machine. Great for compute-heavy workloads where you need tight coordination: training, tuning, batch inference,
real-time serving.

Asya = a Kubernetes-native actor mesh where the topology is declared, not coded. Great for async AI pipelines where you need durability, loose coupling, dynamic routing, and protocol
compliance (A2A/MCP). Every message is persisted to a queue — nothing is lost if a pod dies.

They're complementary more than competitive. You could plausibly run Ray inside an Asya actor for the compute-heavy step, while Asya handles the pipeline orchestration, error routing, and
gateway protocol around it.