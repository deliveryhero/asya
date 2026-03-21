# 🎭 Asya vs Kubernetes GPU Schedulers

**Kueue, Run.ai, Volcano**

## TL;DR

GPU schedulers manage **job admission and resource allocation** — they decide which jobs run on
which GPUs, enforce quotas, and handle preemption. Asya orchestrates **multi-step pipelines**
with queue-based message routing between independent actors. Schedulers answer "when and where
does this job get GPUs?"; Asya answers "how do these processing steps connect and scale?"

## Comparison Table

| Dimension | Kueue | Run.ai | Volcano | 🎭 |
|---|---|---|---|---|
| **Primary purpose** | Job queuing and quota management for K8s | GPU virtualization, scheduling, and multi-tenant platform | Batch scheduling for HPC/AI workloads on K8s | Multi-step AI pipeline routing with independent scaling |
| **Unit of work** | K8s Job, RayJob, PyTorchJob (batch workloads) | GPU workload (interactive, training, inference) | PodGroup (gang-scheduled batch jobs) | Envelope (message routed through actor chain) |
| **What it manages** | Cluster queues, cohorts, resource flavors, quotas | GPU fractioning, scheduling, quotas, node pools | Queue-based fair scheduling, gang scheduling | Message queues, actor scaling, envelope routing |
| **Scaling model** | Admits or suspends entire jobs based on quota | Fractional GPU allocation, dynamic resource pooling | Gang scheduling (all-or-nothing pod groups) | KEDA scales each actor 0-N based on queue depth |
| **Scale to zero** | ⚠️ Jobs complete and release resources (not long-running) | ⚠️ Idle GPU reclamation between workloads | ⚠️ Jobs complete and release resources | ✅ Yes (actors scale to zero between messages) |
| **GPU awareness** | Resource flavor matching (GPU type, count) | Deep GPU virtualization (MIG, fractional, topology) | GPU resource requests via K8s scheduler extender | Delegates to K8s scheduler; actors specify resource requests |
| **Preemption** | Priority-based within/across queues | Workload preemption with GPU-aware bin packing | Preemptable queues, reclaim policies | No preemption (queue-based backpressure instead) |
| **Multi-tenancy** | Cohorts with fair-share borrowing | Full platform: RBAC, projects, departments, quotas | Queue-based fair scheduling | Namespace isolation (standard K8s) |
| **Pipeline support** | ❌ No (schedules independent jobs) | ❌ No (schedules independent workloads) | ⚠️ Limited (job dependencies via DAG plugin) | ✅ Core capability: actors chained via envelope routing |
| **Routing** | ❌ N/A (job admission, not message routing) | ❌ N/A (resource allocation) | ⚠️ Static DAG dependencies between jobs | ✅ Dynamic: actors rewrite `route.next` at runtime |
| **Workload type** | Batch: training, fine-tuning, data processing | Training, inference, notebooks, interactive | HPC: MPI, training, batch analytics | Async pipelines: inference chains, agentic workflows |
| **Long-running services** | ❌ Not designed for (job-oriented) | ✅ Yes (inference endpoints, notebooks) | ❌ Not designed for (batch-oriented) | ✅ Yes (actors are long-running Deployments) |

## When to Use What

**Use Kueue / Run.ai / Volcano when:**

- You need **GPU quota management** — multiple teams sharing a finite GPU cluster with fair-share policies
- You run **batch training jobs** — PyTorch distributed training, Ray Train, fine-tuning runs that need gang scheduling
- You need **preemption** — low-priority jobs yield GPUs to high-priority ones automatically
- Your concern is **cluster utilization** — packing GPU jobs efficiently, fractional GPU allocation

**Use Asya when:**

- You need to **chain processing steps** — preprocess, infer, score, route — not just schedule a single job
- Steps have **different resource profiles** — CPU-bound actors and GPU-bound actors in the same pipeline
- You want **queue-based decoupling** — each step processes at its own pace with backpressure via queue depth
- You need **dynamic routing** — the output of one step determines which step runs next
- Your workload is a **long-running service**, not a batch job — actors stay deployed and scale with demand
