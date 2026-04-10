# Agentic Research Platform: Missing Functionality

With the flow-native model, the gaps collapse to the **same cross-cutting gaps**
that affect all agentic patterns — plus a few platform-specific items.

---

## Shared Gaps (Same as Other Patterns)

These are documented in detail in their respective pattern directories.
Listed here for completeness with pointers:

### P0: Fan-in timeout and partial failure handling

If one of 10 researcher actors hangs (API timeout, LLM rate limit), the fan-in
blocks all 9 completed results indefinitely.

**Details**: `document-processing/missing.md#1`, `document-processing/missing.md#2`

**Impact on research**: A 10-topic research with 1 flaky API call wastes all
9 successful results. Need M-of-N completion policy.

### P0: Max-iteration guard not enforced

The evaluator loop (`while coverage < threshold`) can loop forever if the
evaluator never reaches the threshold.

**Details**: `adaptive-rag/missing.md#1`

**Impact on research**: Runaway research loop consumes compute indefinitely.

### P0: MCP blocking tools/call

Researchers triggering flows via MCP (from Claude Code, Goose, etc.) need
synchronous tool results. Current MCP returns task metadata immediately.

**Details**: `agent-mcp-backend/missing.md#2`

### P1: No input/output schema extraction from Flow DSL

Flows must be manually registered as MCP tools with hand-written schemas.
Researchers can't just compile and have the flow appear as a tool.

**Details**: `agent-mcp-backend/missing.md#1`

### P1: Pause metadata not exposed via A2A GetTask

If a flow includes human approval gates (review experiment plan before
running expensive GPU jobs), external agents can't see what input is required.

**Details**: `long-running-checkpointed/missing.md#1`

---

## Platform-Specific Gaps

### P1-PL-1. No flow deployment CLI (compile + deploy + register in one step)

**Current state**: Deploying a flow requires three manual steps:
1. `asya flow compile research.py` → generates manifests
2. `kubectl apply -f compiled/manifests/` → creates AsyncActor CRDs
3. Update gateway ConfigMap with tool schema → registers as MCP tool

**What's needed**:
- `asya flow deploy research.py` — single command that compiles, applies CRDs,
  and registers the flow as a gateway tool
- Auto-generates MCP tool schema from flow signature (see schema extraction gap)
- Idempotent: re-deploy updates existing actors, doesn't create duplicates

**Effort**: 2-3 weeks (CLI + gateway integration)

### P1-PL-2. State-proxy read-only mount mode for shared datasets

**Current state**: No mount-level read-only flag. Researcher actors could
accidentally overwrite shared datasets.

**Files**:
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml:340-346`
  — `writeMode` has `buffered`/`passthrough` only

**What's needed**:
- `writeMode: readonly` in AsyncActor CRD
- Runtime refuses write operations on read-only mounts

**Effort**: 1-2 days

### P1-PL-3. GPU scheduling in AsyncActor CRD

**Current state**: CRD supports `resources` but no GPU-specific fields.
Requesting GPUs requires raw resource limits that aren't validated.

**What's needed**:
- First-class GPU support: `resources.limits."nvidia.com/gpu": 1`
- Node selector presets: `gpu: a100` in CRD → translated to nodeSelector
- KEDA awareness of GPU availability

**Effort**: 1 week (CRD fields + composition template)

### P1-PL-4. Cost attribution per user/team

**Current state**: Sidecar metrics exist but no `client_id` or team label.
Platform team can't show per-user compute costs.

**What's needed**:
- Sidecar extracts user identity from envelope headers
- Metrics labeled with `client_id`, `team`, `flow_name`
- LLM token usage reported via ABI:
  `yield "SET", ".headers.x-asya-usage", {"tokens": 5000}`
- Dashboard: usage per team over time

**Effort**: 3-4 weeks

### P2-PL-5. Init containers for pre-download

**Current state**: AsyncActor composition doesn't support init containers.
Can't pre-download model weights or clone repos before handler starts.

**Workaround**: Class handler `__init__()` runs at pod startup. Slower but
functional.

**Files**:
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml` — no
  `initContainers` in pod spec

**Effort**: 1-2 weeks (CRD + composition change)

### P2-PL-6. Flow-level progress tracking

**Current state**: FLY events stream per-actor progress. No aggregate view
showing "step 3 of 7, fan-out: 8 of 10 researchers completed."

**What's needed**:
- Gateway derives pipeline progress from envelope `route.prev/curr/next`
- Fan-in progress: track completed slices vs total
- API: `GET /mesh/{id}/pipeline` → `{step: 3, total: 7, fanout: {done: 8, total: 10}}`

**Effort**: 3-4 weeks

---

## What Already Works (No Gaps)

Everything in the flow execution path works today:

- **Fan-out**: `asyncio.gather()` and list comprehensions compile to parallel
  actor dispatch with KEDA scaling
- **Evaluator loops**: `while` with `break` compiles to loop-back routers
- **Conditional routing**: `if/elif/else` compiles to conditional routers
- **Error handling**: `try/except` compiles to resiliency policies
- **State-proxy S3**: Actors read/write artifacts via `open()` patching
- **CAS conflict detection**: Multiple actors writing to same S3 prefix
  get `FileExistsError` on conflicts
- **Exclusive file creation**: `open(path, "x")` → atomic create-if-absent
- **FLY streaming**: Actors stream progress to gateway → SSE to client
- **KEDA autoscaling**: Queue depth triggers pod scaling (0 → N → 0)
- **Secret injection**: Per-namespace secrets via `secretRefs` in CRD
- **Pause/resume**: Human gates via `x-pause`/`x-resume` with S3 checkpoint
- **DLQ routing**: Failed actors route to `x-sump` automatically
- **Retry with backoff**: Sidecar resiliency policies (exponential, linear, constant)

## Priority Summary

| Priority | Gap | Effort | Source |
|---|---|---|---|
| P0 | Fan-in timeout + partial failure | 2-3 weeks | Cross-cutting |
| P0 | Max-iteration guard | 1 week | Cross-cutting |
| P0 | MCP blocking tools/call | 1-2 weeks | Cross-cutting |
| P1 | Flow deploy CLI | 2-3 weeks | Platform |
| P1 | Schema extraction from Flow DSL | 2-3 weeks | Cross-cutting |
| P1 | Read-only mount mode | 1-2 days | Platform |
| P1 | GPU scheduling | 1 week | Platform |
| P1 | Cost attribution | 3-4 weeks | Platform |
| P1 | Pause metadata in GetTask | 1-2 weeks | Cross-cutting |
| P2 | Init containers | 1-2 weeks | Platform |
| P2 | Flow-level progress | 3-4 weeks | Platform |
