# Multi-Model Evaluation: Missing Functionality

## P0 — Blocking

### 1. Fan-in partial failure (same as document-processing)

If one model provider is down, its actor fails. Fan-in has no policy for
proceeding with N-1 results. The judge needs at least 2 candidates to compare.

**What's needed**: Configurable `min_results` on fan-in — proceed when
M of N slices arrive. See `document-processing/missing.md#2`.

### 2. Max-iteration guard for debate loops (same as adaptive-rag)

Debate convergence check might never converge. The while loop needs a
runtime guard. See `adaptive-rag/missing.md#1`.

---

## P1 — Important

### 3. No per-actor timeout differentiation in fan-out

**Current state**: All actors in a fan-out share the envelope's global
deadline. If Claude's actor has a 120s timeout and GPT-4's has 60s, there's
no way to express this in the flow DSL.

**Files**:
- `src/asya-lab/asya_lab/flow/codegen.py` — fan-out generates identical
  headers for all slices
- `src/asya-sidecar/internal/router/` — sidecar reads per-actor timeout
  from CRD, but fan-out envelope carries parent deadline

**What's needed**:
- Per-actor timeout in fan-out: `asyncio.gather(a(p, timeout=60), b(p, timeout=120))`
- Or: rely on CRD-level timeout (already works) but document this clearly
- Fan-in should use `max(actor_timeouts)` as its wait deadline

### 4. No cost/token tracking per model

**Current state**: No built-in mechanism to track LLM token usage or cost
per actor. Platform teams can't show "this evaluation used 50K tokens on
Claude and 30K on GPT-4."

**What's needed**:
- Convention: actors write token counts to `payload["_usage"]["actor_name"]`
- Gateway aggregates usage metadata from terminal envelope
- Metrics labels for model/provider on gateway Prometheus counters

### 5. No streaming from fan-out branches

**Current state**: FLY events from fan-out branches all share the same
task ID. The client receives interleaved tokens from all 3 models with no
way to distinguish which model is generating.

**What's needed**:
- FLY event metadata: `{"source_actor": "claude_writer", "partial": true, "text": "..."}`
- Client-side demuxing by source actor name
- Or: fan-out branches use child task IDs (requires parent-child task model)

---

## P2 — Nice to Have

### 6. No built-in judge/evaluator crew actor

Every voting/debate flow implements its own judge. A reusable `x-judge`
crew actor with configurable criteria (quality, accuracy, conciseness)
would reduce boilerplate.

### 7. No A/B testing infrastructure

For comparing model quality over time, need to route a percentage of traffic
to each model variant and track win rates. This is a higher-level concern
but natural for multi-model evaluation.
