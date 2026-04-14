---
title: Enable Observability for KubeCon Demo
status: working
priority: 1
assignee: Artem Yushkovskiy
tags:
  - type:feature
  - kubecon-demo
  - worktree:.worktrees/observability-initial/ldx4.enable-observability-kubecon-demo
  - branch:observability-initial/ldx4.enable-observability-kubecon-demo
---

## Context

KubeCon demo runs on GKE with Pub/Sub transport. Observability was built
(sidecar metrics, Grafana dashboard, PodMonitor) but never deployed to a
real cluster. Need Prometheus + Grafana running alongside the existing
asya-crew / asya-crossplane / asya-gateway releases.

## Phase 1: Monitoring Stack (Done)

Monitoring stack deployed to GKE cluster in `monitoring` namespace:

- **kube-prometheus-stack v82.10.4** via `helm install asya-monitoring`
- **Grafana** as ClusterIP (port-forward for access, admin/admin)
- **14 actor targets scraped** (all text-improver flow actors + crew actors)
- Dashboard: `deploy/grafana-dashboards/asya-actors-overview.json` loaded via ConfigMap

### Issue: PodMonitor doesn't work without declared containerPorts

The Crossplane Composition renders sidecar containers without a `ports:` section.
PodMonitor with `targetPort: 8080` generates a relabel rule filtering on
`__meta_kubernetes_pod_container_port_number`, which is empty when no port is declared.

**Workaround**: Used `additionalScrapeConfigs` (inline in helm values) with manual
relabel rules that keep pods by `__meta_kubernetes_pod_container_name=asya-sidecar`
and replace `__address__` to append `:8080`.

**Proper fix**: Add `containerPort` with `name: metrics` to the sidecar container
in the Crossplane Composition. This would make PodMonitors work natively.

### Issue: asya-playground chart not tested

The playground umbrella chart has `sampleMonitoring.enabled` support with PodMonitor
and dashboard ConfigMap templates, but:
1. It has never been deployed to a real cluster
2. The PodMonitor template uses `port: metrics` which won't work (same issue above)
3. The chart may have other broken dependencies (needs testing)


## Phase 2: Per-Flow Observability (Spec)

### Goal

Three-level drill-down for Asya observability:

1. **Flows Overview** (new dashboard) — one row per flow, completion rate
2. **Actors Overview** (enhanced existing) — per-actor metrics filtered by flow
3. Actor-level detail via existing panels

Must be demo-impressive (KubeCon narrative) and operationally useful.

### Label Schema

Flow identity is conveyed via pod labels (set by the flow compiler in AsyncActor
manifests). The Crossplane Composition propagates these to the rendered pod spec.

| Label | Values | Present on |
|---|---|---|
| `asya.sh/flow` | flow name (e.g. `text-improver`) | all actors in the flow |
| `asya.sh/role` | `start`, `end` | only entry/exit actors |
| `asya.sh/generated` | `"true"` | only compiler-generated routers |

User handler actors (generator, evaluator, polisher) get just `asya.sh/flow`.
System actors (x-sink, x-sump) have no flow labels.

Design rationale:
- `asya.sh/role=start` (exactly one per flow): universal entry point, used for
  "flow invocations" metric
- `asya.sh/role=end` (one or more per flow): terminal actors before x-sink,
  used for "flow completions" metric. Multiple end actors handle branching
  flows with different exit paths.
- `asya.sh/generated="true"`: compiler-generated routers, hidden by default in
  dashboards to reduce noise (routers add ~1ms latency and always succeed)

### Prometheus Scrape Config Changes

Add relabel rules to promote pod labels into metric labels. Update the
`additionalScrapeConfigs` in the helm values (or the PodMonitor once
containerPort is fixed):

```yaml
relabel_configs:
  # ... existing rules ...
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_flow]
    target_label: flow
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_role]
    target_label: role
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_generated]
    target_label: generated
```

After this change, every `asya_actor_*` metric carries `flow`, `role`, and
`generated` labels when present on the source pod.

### Dashboard 1: "Asya - Flows Overview" (new)

**Purpose**: At-a-glance health across all deployed flows.

**Variables**:
- `datasource`: Prometheus datasource selector
- `namespace`: multi-select, from `label_values(asya_actor_messages_received_total, namespace)`

**Panels**:

| Panel | Type | Query |
|---|---|---|
| Flow Completion Rate | Stat (repeated per flow) | `sum(rate(asya_actor_messages_processed_total{role="end", flow="$flow", status="success"}[5m])) / rate(asya_actor_messages_processed_total{role="start", flow="$flow", status="success"}[5m])` |
| Flow Throughput | Time series | `rate(asya_actor_messages_processed_total{role="start", status="success"}[5m])` grouped by `flow` |
| Flow Error Rate | Time series | `sum by (flow) (rate(asya_actor_messages_failed_total{flow=~".+"}[5m]))` |

Completion rate uses thresholds: green >= 95%, orange >= 80%, red < 80%.

Each flow row links to the Actors Overview dashboard with `var-flow=<name>`.

### Dashboard 2: "Asya - Actors Overview" (enhanced)

**New variables** (added to existing dashboard):
- `flow`: multi-select, from `label_values(asya_actor_messages_received_total, flow)`.
  Default: all. When selected, all panels filter to `flow=~"$flow"`.
- `show_generated`: custom toggle, values `.*` (show all) / empty string (hide).
  Default: hide generated. Applied as `generated!="true"` or `generated=~"$show_generated"`.

**Panel changes**:
- All existing queries gain `flow=~"$flow"` and `generated=~"$show_generated"` filters
- No new panels — the existing throughput, latency, error, scaling panels are
  sufficient when filtered to a specific flow

### No Code Changes Required

The entire design is label-based:
- **Sidecar**: unchanged — already emits all needed metrics
- **Gateway**: unchanged — no Prometheus metrics needed for this phase
- **Compiler**: already generates manifests with `asya.sh/flow` labels; label
  schema refinement (role/generated) is a manifest template change only
- **Prometheus**: scrape config relabeling change
- **Grafana**: new dashboard JSON + modified existing dashboard JSON

### Files to Change

| File | Change |
|---|---|
| `deploy/grafana-dashboards/asya-actors-overview.json` | Add `flow`, `show_generated` variables; add filters to all queries |
| `deploy/grafana-dashboards/asya-flows-overview.json` | New dashboard |
| `deploy/helm-charts/asya-playground/values-gke-pubsub.yaml` | Add flow/role/generated relabel rules to `additionalScrapeConfigs` |
| `deploy/grafana-dashboards/README.md` | Document new dashboard |

### Future Work (Not This Aint)

- Gateway Prometheus metrics (`asya_gateway_task_completed_total{flow, status}`)
  for authoritative completion tracking from the gateway's perspective
- OpenTelemetry tracing for per-invocation trace spans across the full pipeline
- Retry/backoff observability (aints `1fbs`, `n84d`)
- Crossplane Composition: declare sidecar `containerPort: 8080 name: metrics`
  to make PodMonitors work natively

## Remaining Work

- [ ] Fix Crossplane Composition to declare sidecar `containerPort: 8080 name: metrics`
- [x] Fix playground PodMonitor template to use `targetPort` instead of `port`
- [ ] Test asya-playground chart deployment end-to-end
- [x] Update Prometheus scrape config with flow/role/generated relabel rules
- [x] Create "Asya - Flows Overview" dashboard JSON
- [x] Enhance "Asya - Actors Overview" dashboard with flow/generated filters
- [x] Wire new dashboard into playground chart (symlink, ConfigMap, pre-commit hook)
- [x] Deploy updated dashboards to GKE cluster (14 targets scraped, labels verified)
- [ ] Verify end-to-end with text-improver flow (invoke flow, check completion rate)
