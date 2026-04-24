---
title: Add load test Job to asya-quickstart chart
status: merged
priority: 2 # medium
tags:
  - type:feature
---


## Notes

Add Kubernetes Job template to asya-quickstart chart that:
- Sends sample payloads to test actors and flows
- Generates realistic load to demonstrate autoscaling
- Produces metrics visible in Grafana dashboards
- Runs conditionally: `{{ if .Values.loadTest.enabled }}`

Implementation tasks:
1. Create `templates/load-test-job.yaml`
2. Add values:
   - `loadTest.enabled` (default: false)
   - `loadTest.duration` (e.g., "5m")
   - `loadTest.requestsPerSecond` (e.g., 10)
3. Document in README and NOTES.txt
4. Add example script to generate traffic

Dependencies:
- Requires asya-quickstart chart to be merged first (PR #122)
- Should use deployed test actors from the quickstart chart

Benefits:
- Demonstrates KEDA autoscaling in action
- Shows metrics collection and visualization
- Provides realistic demo scenario for evaluations


_Migrated from beads `asya-l6x`_
