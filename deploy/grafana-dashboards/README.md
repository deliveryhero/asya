# Asya Grafana Dashboards

Pre-configured Grafana dashboards for monitoring Asya actors and components.

## Dashboard Organization

All Asya dashboards are organized into the **"Asya"** folder in Grafana for easy discovery and grouped navigation.

## Available Dashboards

### Asya - Actors Overview

**File**: `asya-actors-overview.json`
**UID**: `asya-actors-overview`
**Folder**: Asya

Comprehensive overview dashboard showing:

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
- Message size distribution (received/sent)

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

Deploy dashboard to the "Asya" folder in Grafana:

```bash
kubectl create configmap asya-dashboard \
  -n monitoring \
  --from-file=asya-actors.json=asya-actors-overview.json \
  --dry-run=client -o yaml | \
  kubectl label -f - --local \
    grafana_dashboard=1 \
    grafana_folder=Asya \
    -o yaml | \
  kubectl apply -f -
```

**Labels explained**:
- `grafana_dashboard=1`: Enables Grafana sidecar discovery
- `grafana_folder=Asya`: Places dashboard in "Asya" folder

ConfigMap structure:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
    grafana_folder: "Asya"
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

## Dashboard Links

Each dashboard includes a dropdown menu labeled **"Asya Dashboards"** in the top navigation bar. This dropdown automatically lists all dashboards tagged with `asya`, providing quick navigation between related dashboards.

## Dashboard Variables

The dashboard includes template variables for filtering and customization:

- **Datasource**: Select Prometheus datasource
- **Namespace**: Filter by Kubernetes namespace (multi-select)
- **Queue**: Filter by actor queue name (multi-select)
- **Percentile**: Select percentile for latency metrics (p50, p95, p99)

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
- `asya_actor_message_size_bytes{direction}`
- `asya_actor_active_messages`
- `asya_actor_runtime_errors_total{queue, error_type}`

Operator metrics (controller-runtime):

- `controller_runtime_reconcile_total{controller="asyncactor"}`
- `controller_runtime_reconcile_errors_total{controller="asyncactor"}`
- `controller_runtime_reconcile_time_seconds{controller="asyncactor"}`

See [docs/architecture/observability.md](../../docs/architecture/observability.md) for details.
