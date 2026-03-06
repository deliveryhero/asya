---
title: "Crossplane E2E tech debt: DLQ support, drift detection tests, cold-start scaling"
priority: 2
---

Merged from: 1f3k (DLQ un-xfail), 1fbq (queue health un-skip), 1f2y (scaling cold-start).

## DLQ support (was 1f3k)

Add shared `asya-{namespace}-dlq` SQS queue in asya-crew chart.
Configure SQS Composition to set `redrivePolicy` on actor queues pointing to DLQ.
Remove `@pytest.mark.skip` from:
- `test_poison_message_moves_to_dlq_e2e`
- `test_dlq_preserves_message_metadata_e2e`

## Crossplane drift detection tests (was 1fbq)

Rewrite 4 tests in `test_queue_health_monitoring_e2e.py`:
- Replace "operator recreates queue" framing with "Crossplane reconciles deleted queue"
- Reduce timeout from 360s to configurable `CROSSPLANE_RECONCILE_TIMEOUT_SECONDS` (default 120s)
- Remove `@pytest.mark.skip`

## Cold-start scaling test (was 1f2y)

Add `test_cold_start_backlog_processing` to `test_scaling_performance_e2e.py`:
scale actor to 0, enqueue N messages, assert all complete successfully.
