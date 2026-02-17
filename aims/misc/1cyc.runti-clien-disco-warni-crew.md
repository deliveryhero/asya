---
title: Runtime 'Client disconnected' warnings in crew actors
status: open
priority: 2 # medium
type: task
---

## Symptoms
Crew actors (happy-end, error-end) showing repeated "Client disconnected" warnings in runtime logs:
- Pattern: WARNING messages every ~6-30 seconds
- Context: Sidecar connects to runtime socket but disconnects without processing
- Pods: Running (2/2) but warnings indicate communication issue

## Log Example
```
2026-02-02 15:49:19 - asya.runtime - INFO - Socket server listening on /var/run/asya/asya-runtime.sock
2026-02-02 15:49:19 - asya.runtime - INFO - Runtime ready signal created: /var/run/asya/runtime-ready
2026-02-02 15:49:21 - asya.runtime - WARNING - Client disconnected
2026-02-02 15:49:27 - asya.runtime - WARNING - Client disconnected
```

## Environment
- Cluster: Kind (asya-local)
- Images: asya-crew:latest, asya-sidecar:latest (loaded from local)
- Transport: SQS (LocalStack)
- Handler mode: envelope

## Investigation Needed
- Check sidecar logs for connection errors
- Verify socket permissions (/var/run/asya/asya-runtime.sock)
- Check if sidecar health probes causing disconnects
- Verify handler module exists: handlers.end_handlers.happy_end_handler

## Related
- Pod: happy-end-7c74c8787f-ds5h6 in asya-system namespace
- Similar issue likely in error-end pod


---
_Migrated from beads `asya-csp`_
