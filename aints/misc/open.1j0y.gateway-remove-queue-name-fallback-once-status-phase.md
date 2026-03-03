---
title: "Gateway: remove queue-name fallback once status.phase is stable"
priority: 3 # low
---


## Context

Implemented in PR #193 (`feat(gateway/consumer): parse status.phase`).

`ResultConsumer.processMessage` now reads `status.phase` from the message body to determine
success/failure. For backward compat it falls back to the queue name (`x-sink` → succeeded,
`x-sump` → failed) when the `status` field is absent.

All actors running sidecar >= PR #189 always emit `status.phase`. The fallback is only needed
for in-flight messages during a rolling upgrade.

## What to do

Once PR #193 has been running in production for a release cycle (all sidecars upgraded):

1. In `src/asya-gateway/internal/consumer/consumer.go`, `processMessage`:
   - Remove the `finalStatus := status` initialization line
   - Change `case "":` to an explicit error log + return (malformed message)
   - Remove the two `consumeQueue` goroutine calls that pass `types.TaskStatusSucceeded` /
     `types.TaskStatusFailed` as the `status` parameter
   - Simplify the function signature: drop the `status types.TaskStatus` parameter entirely

2. Update `consumer_test.go`: remove `TestProcessMessage_NoStatusField_FallsBackToQueueName`
   and add a test asserting missing `status.phase` logs an error and skips the update.

## Files

- `src/asya-gateway/internal/consumer/consumer.go` (primary)
- `src/asya-gateway/internal/consumer/consumer_test.go`
