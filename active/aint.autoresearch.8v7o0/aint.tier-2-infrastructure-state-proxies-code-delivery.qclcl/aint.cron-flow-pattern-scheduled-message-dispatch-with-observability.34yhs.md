---
title: "Cron flow pattern: scheduled message dispatch with observability"
status: open
priority: 1 # high
tags: [tier-2, autoresearch, infrastructure, cron, observability]
---

## Context

Asya has no cron/scheduled flow pattern today. The autoresearch memory-curator
("dreaming flow") and other periodic tasks (metrics aggregation, GC) need this.

## Requirements

1. **Scheduled message dispatch**: K8s CronJob that POSTs an envelope to
   asya-gateway at a configured interval. Gateway is the single entry point
   (creates msg ID, trace ID, handles routing). Not directly to MQ.

2. **Observability**: When did each scheduled run execute? What was the result?
   Duration? Failures? Needs integration with OTel tracing/metrics stack.
   Dashboard visibility: list of cron flows, last run time, status, duration.

3. **Configuration**: Defined alongside the flow/actor manifests. A CronFlow CRD
   or a simple K8s CronJob with gateway URL + envelope template.

4. **Idempotency**: If a cron fires while previous run is still executing,
   configurable behavior: skip, queue, or fail.

## Design Considerations

- CronJob + gateway POST is simplest (no new CRD needed)
- But CRD would enable `asya cron list`, status tracking, centralized config
- OTel integration: cron job emits span on dispatch, flow actors propagate trace
- Dashboard: query OTel traces for cron-triggered flows, display in Grafana or
  lightweight custom UI

## Open Questions

- CRD or plain CronJob? CRD is more Asya-native but more work
- OTel collector deployment: shared cluster-wide or per-namespace?
- How to handle cron-triggered flow failures (retry? alert? dead-letter?)
