---
description: "Comparison: Asya vs Flink, Kafka Streams, Spark Streaming — stream processing frameworks"
---

# Stream Processing

**Apache Flink, Kafka Streams, Spark Streaming**

## TL;DR

Stream processing frameworks perform **stateful, continuous computation over infinite data streams** —
windowed aggregations, joins, CEP, exactly-once guarantees over event time. Asya performs **stateless,
discrete message processing** where each envelope is an independent unit of work routed through a
pipeline of actors. Stream processors own the computation model; Asya owns the routing and scaling
of independent steps.

## Comparison Table

| Dimension | Apache Flink | Kafka Streams | Spark Streaming | 🎭 |
|---|---|---|---|---|
| **Primary purpose** | Stateful stream & batch processing | Lightweight stream processing as a library | Micro-batch and continuous stream processing | Multi-step AI/ML pipeline routing |
| **Processing model** | Continuous per-event with managed state | Per-record with local state stores (RocksDB) | Micro-batch (Structured Streaming) or continuous | Discrete envelope: one message in, one message out |
| **State management** | Built-in keyed state, savepoints, checkpoints | Local state stores with changelog topics | Stateful operations via watermarks and checkpoints | Stateless actors; state-proxy sidecar for virtual persistence |
| **Scaling unit** | Task slots within a JobManager | Kafka partition count drives parallelism | Executors managed by Spark cluster manager | Individual actor pods via KEDA, per-queue |
| **Scale to zero** | ❌ No (JobManager always running) | ❌ No (application process must run) | ❌ No (driver + executors always allocated) | ✅ Yes (KEDA scales each actor 0-N based on queue depth) |
| **Windowing** | Event-time windows, watermarks, triggers | Time and session windows | Watermark-based windows | Not applicable (discrete messages, not streams) |
| **Exactly-once** | ✅ End-to-end with checkpoints + 2PC sinks | ✅ Via Kafka transactions | ✅ Via checkpoint offsets | ⚠️ At-least-once via queue visibility timeout; idempotency is the actor's responsibility |
| **Deployment** | Standalone cluster, YARN, or K8s Operator | Embedded in any JVM application | Spark cluster (standalone, YARN, K8s) | Kubernetes-native CRD (AsyncActor) |
| **Language** | Java/Scala (Python via PyFlink) | Java/Scala | Python, Java, Scala, R | Python (handler), Go (sidecar) |
| **Latency** | Sub-second per event | Sub-second per record | Seconds (micro-batch) to sub-second (continuous) | Seconds (queue poll interval + processing time) |
| **Routing** | ❌ Static DAG defined at compile time | ❌ Kafka topic topology | ❌ Static DAG (DataFrame transformations) | ✅ Dynamic: actors rewrite `route.next` at runtime |
| **GPU workloads** | ❌ Not designed for GPU scheduling | ❌ No GPU awareness | ⚠️ Limited (via Spark Rapids plugin) | ✅ First-class: actors scale on GPU node pools independently |

## When to Use What

**Use Flink / Kafka Streams / Spark Streaming when:**

- You process **continuous, unbounded event streams** (clickstream, IoT telemetry, financial ticks)
- You need **windowed aggregations** — count events per 5-minute window, session windows, sliding windows
- You need **stream joins** — enrich events by joining two streams in real time
- You require **exactly-once semantics** with managed checkpoints and savepoints
- Your workload is **high-throughput, low-latency** (millions of events/sec, sub-second)

**Use Asya when:**

- Each message is an **independent unit of work** (enhance an image, score a document, call an LLM)
- Steps have **wildly different latencies** — a CPU preprocessor (10ms) feeding a GPU inference step (30s)
- You need **scale-to-zero** for bursty or batch workloads where idle cost matters
- You want **dynamic routing** — an LLM judge decides the next step based on content
- Your pipeline is an **AI/ML workflow**, not a data stream transformation
