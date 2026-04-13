---
title: Fix success rate metric to include error status
status: merged
priority: 2
tags:
  - type:bug
---

The asya_actor_messages_processed_total metric only tracks successful processing (status=success|empty_response|end_consumed) but never increments for errors. This causes Grafana's Success Rate by Actor dashboard to show 100% even when errors occur.

Fix: Add RecordMessageProcessed(queue, "error") calls in all error handling paths:
- handleErrorResponse (router.go:207)
- Runtime call failures (router.go:332)
- End actor errors (router.go:85)
- Parse errors (router.go:144)
- Validation errors (router.go:156)
- Route mismatch (router.go:297)

This ensures the metric total includes both successes and errors for accurate success rate calculation.


---
**Close reason**: Fixed in PR #130. Added RecordMessageProcessed(queue, 'error') calls in all error handling paths to ensure accurate success rate metrics in Grafana.


---
_Migrated from beads `asya-h9z`_
