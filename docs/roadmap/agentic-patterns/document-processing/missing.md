# Document Processing: Missing Functionality

## P0 — Blocking

### 1. Fan-in has no timeout

**Current state**: Fan-in aggregator waits for all N slices. If one branch
hangs (OCR on a corrupted PDF), the entire batch blocks indefinitely.

**Files**:
- `src/asya-lab/asya_lab/flow/codegen.py:805-811` — fan-in router sets
  `slice_count` but no timeout
- `src/asya-sidecar/internal/router/` — sidecar has per-actor timeout but
  no fan-in-level timeout

**What's needed**:
- Fan-in timeout: proceed with M-of-N results after deadline
- Configurable policy: `fail_fast` (any failure aborts) vs `best_effort`
  (collect whatever arrives) vs `quorum` (N/2+1 required)
- Timeout specified in flow DSL: `p["r"] = [f(x) for x in items], timeout=300`

### 2. Fan-in has no partial failure handling

**Current state**: If 3 of 100 documents fail OCR, the fan-in aggregator
receives 97 results but has no way to report the 3 failures or continue
without them.

**Files**:
- `src/asya-lab/asya_lab/flow/codegen.py` — `_emit_fanout_router()` has no
  failure tracking
- No fan-in aggregator crew actor — aggregation logic is generated inline

**What's needed**:
- Failed slices reported in aggregated result: `p["failures"] = [...]`
- Configurable failure threshold: abort if >10% fail
- Per-slice error metadata (which doc, what error, which attempt)

---

## P1 — Important

### 3. No batch progress tracking

**Current state**: Gateway tracks progress per task (single envelope). For a
batch of 1000 documents, there's no aggregate progress view.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go` — progress per task ID only
- No batch/job concept in gateway

**What's needed**:
- Batch ID that groups multiple envelopes
- Aggregate progress endpoint: `GET /mesh/batch/{id}/progress`
  returning `{total: 1000, completed: 847, failed: 3, in_progress: 150}`
- FLY events for batch-level progress updates

### 4. No priority queue support

**Current state**: All messages in an actor's queue are FIFO. Urgent documents
can't jump the queue ahead of batch processing.

**What's needed**:
- Priority headers on envelopes
- Transport-level priority queue support (RabbitMQ priority queues,
  SQS FIFO with priority group IDs)
- Sidecar priority-aware consumption

### 5. State-proxy C-extension limitation for OCR/ML

**Current state**: State-proxy patches Python builtins but C extensions
(OpenCV, Tesseract Python bindings, torch) bypass patched `open()`.

**Files**:
- `src/asya-runtime/asya_runtime.py:983-1155` — `_install_state_proxy_hooks()`
  patches builtins only

**What's needed**:
- Document the `io.BytesIO()` workaround pattern in actor templates
- Consider FUSE-based mount as alternative for C-extension compatibility
  (higher effort, OS-level integration)

---

## P2 — Nice to Have

### 6. No dead letter introspection API

**Current state**: Failed documents route to `x-sump` (DLQ) but there's no
API to list, inspect, or retry DLQ messages.

**What's needed**:
- `GET /mesh/dlq` — list failed envelopes with error metadata
- `POST /mesh/dlq/{id}/retry` — re-inject into the pipeline
- Dashboard for DLQ triage
