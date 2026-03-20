---
title: Enable Observability for KubeCon Demo
priority: 1 # high
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

## Deployed (2026-03-20)

Monitoring stack deployed to GKE cluster in `monitoring` namespace:

- **kube-prometheus-stack v82.10.4** via `helm install asya-monitoring`
- **Grafana** exposed as LoadBalancer, dashboard auto-discovered in "Asya" folder
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

## Remaining work

- [ ] Fix Crossplane Composition to declare sidecar `containerPort: 8080 name: metrics`
- [ ] Fix playground PodMonitor template to use `targetPort` instead of `port`
- [ ] Test asya-playground chart deployment end-to-end
- [ ] Consider adding gateway metrics (currently not instrumented)
