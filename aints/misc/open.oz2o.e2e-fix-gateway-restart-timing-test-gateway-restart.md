---
title: "E2E: fix gateway restart timing in test_gateway_restart_during_processing"
priority: 3 # low
---

test_gateway_restart_during_processing is skipped due to 'Gateway restart causes task timeout - timing issue in test environment'. The test sends a message to a slow actor, restarts the gateway pod, and expects the task to complete. The timeout is likely too short or the gateway recovery takes longer than expected. Needs investigation.
