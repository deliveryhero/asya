---
title: "Integration tests: full actor pipeline with state access"
priority: 2 # medium
type: task
---

Integration tests validating stateful actors in a full pipeline context.

Test setup:
- Docker Compose with sidecar + runtime + connector + message queue + MinIO/Redis
- Multiple actors in a pipeline, some with state mounts
- Tests run inside Docker Compose

Test scenarios:
- Actor reads state, processes message, writes updated state
- Pipeline with multiple actors sharing a state backend
- State persists across messages (read state written by previous message)
- Multiple mounts: actor with both meta (Redis) and media (S3) state
- Actor without stateProxy works unchanged (backward compatibility)
- Handler uses standard Python I/O (open, os.path.exists, os.listdir)
- Error propagation: connector error -> runtime exception -> sidecar nack -> requeue

Location: testing/integration/stateful-actors/

Phase: 5 (Testing and documentation)
