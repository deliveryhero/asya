
# How to Debug an Envelope

This guide covers practical steps for tracing an envelope through the Asya
mesh, diagnosing failures, and identifying performance bottlenecks.

## Find the envelope by trace ID

Every envelope carries a `trace_id` in its headers. Use it to grep across pod
logs:

```bash
# Search all actor pods in the namespace for a trace ID
kubectl logs -n my-project -l asya.sh/actor --all-containers | grep "t-42"
```

If you know which actor the envelope should have reached:

```bash
kubectl logs -n my-project deployment/inference -c asya-sidecar | grep "t-42"
kubectl logs -n my-project deployment/inference -c asya-runtime | grep "t-42"
```

## Check the gateway task status

If the envelope was submitted through the gateway, query the task by ID:

```bash
curl http://<gateway-api>/tasks/<task-id>
```

The response shows the current status, which actor is processing, and how many
actors have completed:

```json
{
  "id": "5e6fdb2d-...",
  "status": "running",
  "current_actor_name": "inference",
  "actors_completed": 1,
  "total_actors": 3
}
```

Terminal statuses are `succeeded`, `failed`, `paused`, and `canceled`.

## Inspect the runtime directly with curl

You can bypass the sidecar and invoke the runtime's `/invoke` endpoint
directly from within the pod. This isolates handler issues from queue/routing
issues.

```bash
kubectl exec -n my-project deployment/inference -c asya-runtime -- \
  curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "id": "dbg-1",
    "route": {"prev": [], "curr": "inference", "next": []},
    "payload": {"text": "test input"}
  }'
```

**Interpreting responses**:

| HTTP status | Meaning | Next step |
|-------------|---------|-----------|
| `200` | Handler returned successfully | Inspect `frames` array for output |
| `204` | Handler returned `None` (abort) | Intentional pipeline exit |
| `400` | Malformed input | Check envelope JSON structure |
| `500` | Handler exception | Read `details.traceback` for the stack trace |

Check handler readiness:

```bash
kubectl exec -n my-project deployment/inference -c asya-runtime -- \
  curl --unix-socket /var/run/asya/asya-runtime.sock http://localhost/healthz
```

**Reference**: [Sidecar-Runtime Protocol](../reference/specs/sidecar-runtime.md)
for the full endpoint specification.

## Check x-sink and x-sump

### x-sink (successful completions)

Envelopes that finish the pipeline land in `x-sink`. Check its logs for the
final payload:

```bash
kubectl logs -n my-project deployment/x-sink -c asya-runtime --tail=50
```

### x-sump (errors)

Envelopes that raised an exception or timed out are routed to `x-sump`. The
error details (type, message, traceback) are included in the envelope:

```bash
kubectl logs -n my-project deployment/x-sump -c asya-runtime --tail=50
```

A growing `x-sump` queue signals systematic handler failures. Monitor its
queue depth:

```promql
keda_scaler_metrics_value{scaledObject=~".*x-sump.*"}
```

## Identify bottlenecks with Prometheus metrics

The sidecar exposes Prometheus metrics on `:8080/metrics`. Use these queries
to find where envelopes are slow or failing.

### Throughput per actor

```promql
rate(asya_actor_messages_processed_total{queue="asya-my-project-inference"}[5m])
```

### P95 processing latency (total)

Includes queue receive, runtime execution, and queue send:

```promql
histogram_quantile(0.95,
  rate(asya_actor_processing_duration_seconds_bucket{queue="asya-my-project-inference"}[5m])
)
```

### P95 runtime latency (handler only)

Isolates handler execution time from infrastructure overhead:

```promql
histogram_quantile(0.95,
  rate(asya_actor_runtime_execution_duration_seconds_bucket{queue="asya-my-project-inference"}[5m])
)
```

### Error rate by reason

```promql
sum by (reason) (
  rate(asya_actor_messages_failed_total{queue="asya-my-project-inference"}[5m])
)
```

Reasons include: `parse_error`, `runtime_error`, `transport_error`,
`validation_error`, `route_mismatch`.

### Queue depth

```promql
keda_scaler_metrics_value{scaledObject="inference"}
```

A high queue depth with max replicas running suggests the actor is
under-provisioned.

**Reference**: [Monitoring](../setup/ops-observability.md) for the full metrics
catalog, ServiceMonitor configuration, and alerting rules.

## Common failure patterns

### Envelope stuck in "running"

1. Check the actor's sidecar logs for errors
2. Check if the runtime timed out (look for `context.DeadlineExceeded`)
3. Verify the actor pod is healthy: `kubectl get pods -n my-project -l asya.sh/actor=inference`

### Envelope landed in x-sump

1. Read the x-sump logs for the error type and traceback
2. Reproduce the failure by curling `/invoke` with the same payload
3. Fix the handler and redeploy

### Envelope disappeared

1. Check if the actor returned `None` (routes to x-sink, not x-sump)
2. Check if the SLA deadline expired (routes to x-sink with `phase=failed`, `reason=Timeout`)
3. Verify queue connectivity: check sidecar logs for transport errors

### Timeout crashes

When the runtime exceeds `ASYA_RESILIENCY_ACTOR_TIMEOUT`, the sidecar sends
the envelope to x-sump and crashes the pod. Look for:

```bash
kubectl logs -n my-project deployment/inference -c asya-sidecar --previous | grep "deadline exceeded"
```

The pod restarts automatically. To prevent repeated crashes, either increase
the timeout or optimize the handler.

## Next steps

- [Monitoring](../setup/ops-observability.md) -- Prometheus alerting and Grafana dashboards
- [Sidecar-Runtime Protocol](../reference/specs/sidecar-runtime.md) -- protocol details
- [Troubleshooting](../setup/ops-troubleshooting.md) -- common operational issues
