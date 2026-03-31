# Shared State Collaboration: Missing Functionality

## P0 — Blocking

### 1. No state change notifications (watch/subscribe)

**Current state**: State-proxy is pull-only. If actor A writes a file, actor B
must poll to discover the change. No pub/sub, no filesystem watches, no
event stream for state mutations.

**Files**:
- `src/asya-state-proxy/asya_state_proxy/interface.py` — `StateProxyConnector`
  ABC has no watch/subscribe method
- `src/asya-state-proxy/asya_state_proxy/server.py` — HTTP server has no
  event endpoints

**What's needed**:
- State change events: connector emits notification on write/delete
- Options: (a) SSE endpoint on connector for subscribers, (b) queue message
  on state change, (c) Redis SUBSCRIBE for Redis backend
- External agents could subscribe to state changes instead of polling

**Workaround**: Actors communicate state changes through envelope routing
(message passing), not shared state observation.

### 2. No external access API for state-proxy contents

**Current state**: State-proxy is accessible only from within actor pods via
Unix socket. External agents can't browse or read state contents through the
gateway.

**Files**:
- `src/asya-gateway/internal/` — no endpoints for state-proxy access
- MCP resources (which would be the natural integration) not implemented

**What's needed**:
- Gateway endpoint: `GET /mesh/state/{mount}/{key}` — read state file
- Gateway endpoint: `GET /mesh/state/{mount}/?prefix=X` — list state files
- MCP resources integration: `asya://state/{mount}/{key}`
- Presigned URL generation endpoint for external download

---

## P1 — Important

### 3. No multi-key atomic operations

**Current state**: Each `open()` / `os.unlink()` is an independent operation.
Can't atomically update two related files (e.g., update index + write data).

**Files**:
- `src/asya-state-proxy/asya_state_proxy/connectors/` — all connectors
  handle single-key operations

**What's needed**:
- Transaction context: `with state_transaction("/state/mount") as tx:` that
  buffers writes and commits atomically
- Or: document that multi-key atomicity is out of scope — use envelope
  routing for coordination instead

### 4. No versioning / history for state files

**Current state**: CAS detects conflicts but doesn't maintain version history.
Overwritten files are gone. No way to roll back to a previous version.

**What's needed**:
- S3 versioning integration: connector reads `user.asya.version_id` xattr
- List versions: `os.listxattr("/state/file", "user.asya.versions")` returns
  version IDs
- Read specific version: convention TBD (version ID in path? xattr?)

### 5. C-extension compatibility gap

**Current state**: State-proxy patches Python builtins only. Libraries using
C extensions (pandas, numpy, torch) bypass patches.

**Files**:
- `src/asya-runtime/asya_runtime.py:983-1155` — patches `builtins.open`,
  `os.stat`, etc. but not `os.open` or C-level `fopen()`

**Documented workaround**: Read via `open()`, wrap in `io.BytesIO()`:
```python
with open("/state/weights/model.bin", "rb") as f:
    data = f.read()
model = torch.load(io.BytesIO(data))
```

**Alternative (higher effort)**: FUSE-based mount that intercepts at OS level.
Would support all libraries but requires privileged containers.

---

## P2 — Nice to Have

### 6. No state quota enforcement

**What's needed**:
- Per-actor storage quotas (max 1GB per mount)
- Alerts on quota approaching
- Platform teams control storage costs

### 7. No state garbage collection

**What's needed**:
- TTL support for S3/GCS (currently Redis-only via xattr)
- Lifecycle policies: auto-delete artifacts older than N days
- Or: document that users should configure S3 lifecycle rules directly
