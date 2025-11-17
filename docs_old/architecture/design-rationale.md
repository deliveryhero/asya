# Design Rationale

Why Asya🎭 uses sidecar pattern and async communication.

## Why Sidecar Pattern?

### Performance

**Unix Socket Benefits:**
- Low latency: ~1-2μs (vs ~100μs TCP)
- High throughput: >10GB/s (vs 1-2GB/s TCP)
- No network overhead

For AI workloads with large tensors:
```
100MB model output:
  Unix socket: ~10ms
  TCP:         ~50-100ms
  Network:     ~1000ms
```

**Language Independence:**
- Runtime in any language (Python, Rust, C++, Java)
- No queue client libraries needed
- Sidecar handles all queue protocols

### Decoupling

**Separation:**
- Runtime: Business logic, inference
- Sidecar: Queue handling, routing, retries

**Independent Scaling:**
```yaml
sidecar:
  resources:
    cpu: 100m       # Low CPU for routing
    memory: 64Mi

runtime:
  resources:
    cpu: 4000m      # High CPU/GPU for inference
    memory: 16Gi
    nvidia.com/gpu: 1
```

**Benefits:**
- Upgrade sidecar without changing runtime
- Change queue systems without rewriting apps
- Test runtime in isolation (no queue mocking)
- Add metrics/tracing centrally

### Operational

- **Centralized monitoring**: Single metrics exporter
- **Security**: Sidecar holds credentials, runtime firewalled
- **Deployment**: Operator auto-injects sidecar

## Why Async Communication?

### Scale to Zero

**Traditional sync:**
- Always-on pods (minimum 2-3 for HA)
- Idle pods waste money

**Async with KEDA:**
- Scale to ZERO when idle
- Pay only for work

**Cost example (GPU @ $1/hour):**
```
Sync (3 pods always-on):  $2,160/month
Async (8h/day usage):     $240/month
Savings: 89%
```

**KEDA Scaling:**
```
0 messages  → 0 pods  (scale to zero)
10 messages → 2 pods  (10/queueLength=5)
50 messages → 10 pods (rapid scale-up)
```

### Pull-Based Consumption

**Sync (push):**
- API must handle backpressure
- Reject with 429 errors
- Lost requests

**Async (pull):**
- Actor pulls when ready
- Queue buffers messages
- Natural backpressure
- No rejected requests

**Burst handling:**
```
Sync:  1000 requests → Overload → 503 errors
Async: 1000 messages → Queue buffers → KEDA scales → All processed
```

### Reliability

**At-least-once delivery:**
1. Sidecar receives message
2. If crash → Message returns to queue
3. Retry automatically
4. ACK only on success

**Error handling:**
- Success → Next actor
- Error → error-end queue
- Monitor error-end for alerts

## Trade-Offs

### When to Use Sync

- Low latency required (<100ms)
- Simple request-response
- Always-on service needed
- External clients without queue access

**Solution:** Use Asya🎭 Gateway (sync interface, async backend)

### When to Use Async

- Batch processing
- Variable/bursty workload
- Long processing (>1s)
- Multi-actor pipelines
- Cost optimization (scale to zero)
- GPU workloads

## Summary

| Benefit | Sidecar | Async |
|---------|---------|-------|
| Performance | Unix sockets (low latency) | - |
| Cost | - | Scale to zero (89% savings) |
| Decoupling | Language independent | - |
| Reliability | - | At-least-once delivery |
| Scalability | - | KEDA autoscaling |
| Simplicity | No app code changes | Natural backpressure |

## Next Steps

- [Architecture Overview](overview.md) - System architecture
- [Sidecar Architecture](asya-sidecar.md) - Detailed sidecar design
- [Core Concepts](../getting-started/concepts.md) - Understanding Asya🎭
