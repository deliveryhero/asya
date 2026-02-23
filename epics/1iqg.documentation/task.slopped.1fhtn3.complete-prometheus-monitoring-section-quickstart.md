---
title: Complete Prometheus monitoring section in quickstart
priority: 2 # medium
type: task
tags:
  - beads:epic:asya-ln2
---





Expand the Prometheus section (line 549) in docs/quickstart/README.md:

1. Deploy kube-prometheus-stack with Helm (includes Prometheus + Grafana)
2. Create ServiceMonitors for:
   - asya-operator metrics (:8080/metrics)
   - asya-gateway metrics (if gateway exposes them)
   - asya-actor sidecars (via pod label selectors)
3. Import pre-built Grafana dashboards (from deploy/grafana-dashboards/)
4. Port-forward Grafana (default creds: admin/prom-operator)
5. Verification steps:
   - Call actors via MCP gateway (asya mcp call hello --name=Test)
   - Open Grafana dashboard
   - Verify metrics appear: message counts, processing times, active actors
6. Add screenshots or expected output examples

Ensure all bash commands are testable (they're run by testing/e2e/tests/test_quickstart_readme.py).


---
_Migrated from beads `asya-2jb`_
