---
title: Test Prometheus + Grafana setup in local Kind cluster
status: open
priority: 2 # medium
type: task
dependencies:
  - misc/1cf3
---

Manually test the complete observability setup following the quickstart README:

1. Create fresh Kind cluster (kind-asya-local)
2. Install minimal setup (KEDA, LocalStack, operator, hello actor)
3. Install S3 + crew actors
4. Install gateway + PostgreSQL
5. Install Prometheus + Grafana
6. Verify metrics flow:
   - Port-forward gateway, call actors via MCP
   - Port-forward Grafana, view dashboards
   - Confirm metrics show: message throughput, processing times, active pods
7. Test autoscaling scenario (send 25 messages, watch metrics)
8. Document any issues or improvements needed

This validates the quickstart instructions work end-to-end before users try them.


---
_Migrated from beads `asya-a65`_
