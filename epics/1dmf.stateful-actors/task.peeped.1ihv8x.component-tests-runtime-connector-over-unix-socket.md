---
title: "Component tests: runtime <-> connector over Unix socket"
priority: 2 # medium
type: task
---


Component tests validating runtime interception layer communicates correctly with a connector over Unix socket.

Test setup:
- Docker Compose with runtime container + s3-buffered-lww connector + MinIO
- Runtime configured with ASYA_STATE_PROXY_MOUNTS
- Tests run inside Docker Compose (no port-forwarding)

Test cases:
- open() read: handler reads file from state mount, data comes from MinIO via connector
- open() write + close: handler writes file, data appears in MinIO
- os.path.exists(): returns True for existing keys, False for missing
- os.listdir(): lists keys under prefix
- os.remove(): deletes key from backend
- os.makedirs(): no-op for state paths
- Error handling: FileNotFoundError on missing key, proper exception mapping
- Text mode: encoding/decoding works correctly
- Binary mode: raw bytes pass through

Location: testing/component/state-proxy/

Phase: 5 (Testing and documentation)
