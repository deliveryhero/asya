# Grafana Dashboards

Pre-configured Grafana dashboards for monitoring Asya actors.

## Available Dashboards

### asya-actors.json

Comprehensive dashboard showing:

**Message Throughput**
- Message rate (received, processed, sent)
- Active messages gauge

**Performance**
- Processing duration percentiles (p50, p95, p99)
- Runtime execution duration percentiles

**Errors**
- Message failures by reason
- Runtime errors by type

**Message Sizes**
- Envelope size distribution (received/sent)

**Operator Health**
- Reconciliation rate and errors
- Reconciliation duration percentiles

## Installation

### Import to Grafana

1. Open Grafana UI
2. Navigate to Dashboards → Import
3. Upload `asya-actors.json`
4. Select your Prometheus datasource
5. Click Import

### ConfigMap Installation (Kubernetes)

```bash
kubectl create configmap asya-grafana-dashboards \
  --from-file=asya-actors.json \
  -n monitoring
```

Add label for Grafana sidecar discovery:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-grafana-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  asya-actors.json: |
    <dashboard JSON content>
```

### Prometheus Configuration

Ensure Prometheus scrapes asya-sidecar metrics:

```yaml
scrape_configs:
- job_name: asya-actors
  kubernetes_sd_configs:
  - role: pod
  relabel_configs:
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_actor]
    action: keep
    regex: .+
  - source_labels: [__meta_kubernetes_pod_container_name]
    action: keep
    regex: asya-sidecar
  - source_labels: [__address__]
    action: replace
    regex: ([^:]+)(?::\d+)?
    replacement: $1:8080
    target_label: __address__
```

## Dashboard Variables

The dashboard includes template variables for filtering:

- **Datasource**: Select Prometheus datasource
- **Namespace**: Filter by Kubernetes namespace (multi-select)
- **Queue**: Filter by queue name (multi-select)

## Metrics Reference

All metrics exposed by asya-sidecar at `:8080/metrics`:

- `asya_actor_messages_received_total{queue, transport}`
- `asya_actor_messages_processed_total{queue, status}`
- `asya_actor_messages_sent_total{destination_queue, message_type}`
- `asya_actor_messages_failed_total{queue, reason}`
- `asya_actor_processing_duration_seconds{queue}`
- `asya_actor_runtime_execution_duration_seconds{queue}`
- `asya_actor_queue_receive_duration_seconds{queue, transport}`
- `asya_actor_queue_send_duration_seconds{destination_queue, transport}`
- `asya_actor_envelope_size_bytes{direction}`
- `asya_actor_active_messages`
- `asya_actor_runtime_errors_total{queue, error_type}`

Operator metrics (controller-runtime):

- `controller_runtime_reconcile_total{controller="asyncactor"}`
- `controller_runtime_reconcile_errors_total{controller="asyncactor"}`
- `controller_runtime_reconcile_time_seconds{controller="asyncactor"}`

See [docs/architecture/observability.md](../../docs/architecture/observability.md) for details.
