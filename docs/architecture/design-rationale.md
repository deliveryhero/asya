# Design Rationale

Why Asya uses sidecar pattern and async communication.

## Why Sidecar Pattern?

The sidecar pattern separates message routing from application logic, providing significant benefits for AI workloads.

### 1. Performance

**High-Performance Communication**

Unix domain sockets provide:
- **Zero network overhead**: No TCP/IP stack traversal
- **Zero serialization cost**: Direct memory transfer between processes
- **Low latency**: ~1-2μs vs ~100μs for localhost TCP
- **High throughput**: >10GB/s on modern systems

**Benchmarks (typical):**
```
Unix socket:    1-2 μs latency, 10+ GB/s throughput
Localhost TCP:  100 μs latency, 1-2 GB/s throughput
Network TCP:    1-10 ms latency, 100 MB/s - 10 GB/s throughput
```

For AI workloads processing large tensors/embeddings, this matters:
```
100MB model output via Unix socket:  ~10ms
100MB model output via TCP:          ~50-100ms
100MB model output via network:      ~1000ms
```

**No Application Code Changes**

- Runtime code focuses purely on inference/processing
- No queue client libraries to install
- No message format knowledge required
- Simple stdin/stdout-like interface

**Language Independence**

- Runtime can be in any language (Python, Rust, C++, Java)
- Sidecar handles all queue-specific protocols
- No polyglot queue client maintenance

### 2. Decoupling

**Separation of Concerns**

```
┌────────────────────────┐  ┌──────────────────────────┐
│     Your Runtime       │  │        Sidecar           │
│   (Business Logic)     │  │   (Infrastructure)       │
├────────────────────────┤  ├──────────────────────────┤
│ • Model inference      │  │ • Queue connections      │
│ • Data processing      │  │ • Message routing        │
│ • Business rules       │  │ • Error handling         │
│ • Validation           │  │ • Retries                │
│                        │  │ • Metrics                │
│                        │  │ • Timeouts               │
└────────────────────────┘  └──────────────────────────┘
```

**Independent Scaling**

- Sidecar resources: Low CPU, moderate memory
- Runtime resources: High CPU/GPU, high memory
- Tune each independently:
  ```yaml
  sidecar:
    resources:
      cpu: 100m      # Low CPU for message routing
      memory: 64Mi

  runtime:
    resources:
      cpu: 4000m     # High CPU/GPU for inference
      memory: 16Gi
      nvidia.com/gpu: 1
  ```

**Independent Evolution**

- Upgrade sidecar without touching runtime code
- Change queue systems without rewriting applications
- Add new features (metrics, tracing) centrally
- Fix bugs in routing logic once, apply everywhere

**Testing Simplicity**

```python
# Test runtime in isolation - no queue setup needed
def test_process():
    result = process({"text": "hello"})
    assert result["output"] == "HELLO"

# No mocking of queue clients
# No integration test complexity
# Pure unit tests
```

### 3. Operational Benefits

**Centralized Monitoring**

- Single metrics exporter (sidecar)
- Consistent metric names across all actors
- No application code changes for observability
- Centralized logging format

**Security Isolation**

- Sidecar holds queue credentials
- Runtime has no network access (can be firewalled)
- Secrets managed in one place
- Principle of least privilege

**Deployment Simplicity**

Operator automatically injects sidecar:
```yaml
# You write
apiVersion: asya.io/v1alpha1
kind: AsyncActor
spec:
  workload:
    template:
      spec:
        containers:
        - name: runtime
          image: my-app:latest

# Operator creates
# Pod with sidecar automatically injected
# No manual YAML editing required
```

## Why Async Communication?

Async queue-based communication enables unique capabilities for AI workloads.

### 1. Auto-Scaling from 0 to N

**Cost-Efficient Scaling**

Traditional sync APIs:
```
Load Balancer → [Pod1, Pod2, Pod3, ...]
- Always-on pods (minimum 2-3 for HA)
- Idle pods waste money
- Slow cold starts for scale-up
```

Async with KEDA:
```
Queue → KEDA → [Pod1, Pod2, ..., PodN]
- Scale to ZERO when idle
- Pay only for actual work
- Fast scale-up based on queue depth
```

**Example cost savings (GPU workload):**
```
Sync API (3 GPU pods always-on):
3 pods × $1/hour × 24 hours × 30 days = $2,160/month

Async (scale to zero, 8h/day actual usage):
1 pod × $1/hour × 8 hours × 30 days = $240/month
Savings: $1,920/month (89% reduction)
```

**Intelligent Scaling**

KEDA monitors queue depth and scales based on actual demand:
```
Queue depth:  0 msgs → 0 pods  (scale to zero)
Queue depth: 10 msgs → 2 pods  (10 / queueLength=5)
Queue depth: 50 msgs → 10 pods (rapid scale-up)
Queue depth:  5 msgs → 1 pod   (gradual scale-down)
```

**Scaling policies:**
- **Scale up**: Aggressive (100% increase or +4 pods every 15s)
- **Scale down**: Conservative (50% decrease, 60s stabilization)
- **Scale to zero**: After cooldown period (60-120s)

### 2. No Rate Limiting

**Pull-Based Consumption**

Sync (push-based):
```
Client → [Rate Limiter] → API → Actor
- Must handle backpressure
- Reject requests when overloaded
- Clients get 429 errors
- Lost requests or retry complexity
```

Async (pull-based):
```
Client → Queue → Actor pulls when ready
- Natural backpressure
- Queue buffers messages
- No rejected requests
- Actor pulls at its own pace
```

**Adaptive Throughput**

Each actor pulls only what it can process:
```python
# Sidecar configured with prefetch=1
while True:
    msg = receive()      # Waits for capacity
    process(msg)         # Takes 10s for GPU inference
    ack(msg)             # Only then pulls next message

# No overload - actor sets its own pace
# No rate limiting needed
# No backpressure complexity
```

**Burst Handling**

Sync:
```
1000 requests arrive simultaneously → API overloaded → 503 errors
```

Async:
```
1000 messages arrive simultaneously → Queue buffers → KEDA scales up
- Messages wait in queue
- Actors scale up automatically
- All messages processed eventually
- No errors, no lost data
```

### 3. Natural Backpressure

**Queue as Buffer**

The queue naturally buffers work:
```
Producer rate: 1000 msgs/second
Consumer capacity: 100 msgs/second

Sync: 900 requests rejected
Async: Queue grows, triggers scaling, eventually catches up
```

**Prefetch Control**

Sidecar pulls only what runtime can handle:
```yaml
ASYA_RABBITMQ_PREFETCH: 1  # One message at a time
```

Runtime processes at its own pace:
- Fast models: High throughput
- Slow models: Lower throughput
- GPU models: Limited by GPU
- No artificial rate limits needed

**Self-Regulating**

System automatically adapts:
```
1. Queue depth increases
2. KEDA notices
3. More pods start
4. Queue depth decreases
5. KEDA scales down
6. Equilibrium reached
```

### 4. Reliability and Fault Tolerance

**At-Least-Once Delivery**

Messages are not lost:
```
1. Sidecar receives message
2. Message marked "in-flight"
3. Runtime processes
4. If crash → message returns to queue
5. Retry automatically
6. ACK only on success
```

**Graceful Degradation**

```
Actor pod crashes:
- Message returns to queue
- KEDA maintains other pods
- Message reprocessed elsewhere
- No user-visible error

Queue unavailable:
- Messages buffer in queue
- Actors retry connection
- Processing resumes when queue returns
```

**Error Handling**

Errors go to dedicated queue:
```
Message processing:
  Success → next step in pipeline
  Error → error-end queue
  Timeout → error-end queue

Monitor error-end queue
Alert on error rate
Debug failed messages
```

## Real-World Example

### Traditional Sync API

```python
# API server
@app.post("/process")
def process_request(data):
    # Need rate limiting
    if rate_limiter.exceeded():
        return 429

    # Need timeout handling
    try:
        result = model.infer(data, timeout=10)
    except Timeout:
        return 504

    # Always-on cost
    return result

# Deployment
replicas: 3  # Always running
cost: High
scaling: Manual or HPA (slow)
```

### Asya Async Actor

```python
# Runtime (no infrastructure code)
def process(payload):
    return model.infer(payload)

# That's it!
```

```yaml
# Deployment
apiVersion: asya.io/v1alpha1
kind: AsyncActor
spec:
  scaling:
    minReplicas: 0     # Scale to zero
    maxReplicas: 50    # Scale to demand
    queueLength: 5     # Adaptive

# Result
cost: Pay per use
scaling: Automatic
reliability: Built-in
```

**Cost comparison (GPU workload):**
```
Sync API:
- 3 pods × 24h × $1/h = $72/day
- Mostly idle
- 100% uptime cost

Async Actor:
- 0-10 pods based on demand
- Average 2 pods × 8h × $1/h = $16/day
- 78% cost reduction
- Better performance during bursts
```

## Trade-Offs

### When to Use Sync (HTTP/gRPC)

- **Low latency required** (<100ms response time)
- **Request-response pattern** needed
- **Simple request routing** (no pipelines)
- **Always-on service** required
- **External clients** (no queue access)

**Solution:** Use Asya Gateway for sync interface, async backend

### When to Use Async (Asya)

- **Batch processing** (large volumes)
- **Variable workload** (bursty traffic)
- **Long processing** (>1s per request)
- **Pipeline processing** (multi-step)
- **Cost optimization** (scale to zero)
- **GPU workloads** (expensive, need efficiency)

## Hybrid Pattern

Best of both worlds:

```
Client → Gateway (Sync) → Queue → Actor (Async) → Queue → Gateway → Client
         └─ Job tracking
         └─ SSE streaming
```

**Benefits:**
- Sync API for clients (familiar)
- Async processing (cost-efficient)
- Job tracking and status
- Real-time updates via SSE
- Scale to zero when idle

## Summary

**Sidecar Pattern:**
- ✅ High performance (Unix sockets)
- ✅ Language independence
- ✅ Separation of concerns
- ✅ Centralized infrastructure
- ✅ Easy testing

**Async Communication:**
- ✅ Scale to zero (cost savings)
- ✅ Natural backpressure (no rate limiting)
- ✅ Burst handling (queue buffering)
- ✅ Reliability (at-least-once delivery)
- ✅ Adaptive throughput (pull-based)

**Result:** Cost-efficient, scalable, reliable AI workload platform

## Next Steps

- [Architecture Overview](overview.md) - System architecture
- [Sidecar Architecture](sidecar.md) - Detailed sidecar design
- [Core Concepts](../getting-started/concepts.md) - Understanding Asya
