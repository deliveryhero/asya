# Guardrailed Production: Missing Functionality

## P0 — Blocking

### 1. Exception type matching is name-only

**Current state**: Parser extracts exception type names as strings
(`['ValueError', 'ConnectionError']`) but doesn't validate that actors can
raise these types or link them to sidecar resiliency policies.

**Files**:
- `src/asya-lab/asya_lab/flow/parser.py:1100-1124` —
  `_extract_exception_types()` returns string names only
- `src/asya-sidecar/internal/router/` — sidecar matches error strings from
  runtime response against policy patterns

**What's needed**:
- Compiler should generate sidecar resiliency rules that map exception types
  to except-block routing
- Runtime should propagate exception type name in error response headers
  (currently sends generic error message)
- Sidecar should match `error_type` header against compiled policy rules

**Current workaround**: Try/except compiles to a single catch-all. All errors
route to the same except handler. No typed exception routing.

### 2. No named exception binding (`except E as e`)

**Current state**: Parser explicitly rejects `except ValueError as e:` syntax.
Except handlers can't access the error details.

**Files**:
- `src/asya-lab/asya_lab/flow/parser.py:1067-1069` — raises FlowCompileError

**What's needed**:
- Error metadata written to payload by sidecar:
  `p["_error"] = {"type": "ValueError", "message": "...", "actor": "pii_detector"}`
- Except handler reads `p["_error"]` to decide recovery strategy
- Or: ABI `yield "GET", ".status.error"` to read error details

---

## P1 — Important

### 3. No reusable guardrail actors (crew library gap)

**Current state**: Every flow implements its own validators. No shared
guardrail actors for common patterns.

**What's needed** (crew actor library):
- `x-validate-schema` — JSON Schema validation of payload fields
- `x-detect-pii` — PII detection with configurable entity types
- `x-filter-content` — content safety filtering (toxicity, bias, harmful)
- `x-check-policy` — rule-based policy engine (configurable via ConfigMap)

These would be deployed as part of `asya-crew` chart, available to all flows.

### 4. No guardrail bypass for internal/trusted callers

**Current state**: All requests pass through all guardrails. Internal
service-to-service calls (already authenticated, pre-validated) waste
resources on redundant validation.

**What's needed**:
- Trust level headers: `x-asya-trust: internal` skips input validation
- Configurable per-guardrail: "skip if trust >= internal"
- Gateway sets trust level based on auth context (OAuth scope, API key type)

### 5. No guardrail metrics/alerting

**Current state**: No metrics on guardrail pass/fail rates. Can't alert on
"PII detection blocking 40% of requests" (likely a bug, not real PII).

**What's needed**:
- Per-guardrail Prometheus counters: `asya_guardrail_passed_total`,
  `asya_guardrail_blocked_total` with labels `{guardrail, reason}`
- Alerting rules for anomalous block rates

---

## P2 — Nice to Have

### 6. No try/except/finally support

**Current state**: `try/finally` without `except` is rejected. `else` on
try/except is also rejected.

**Files**:
- `src/asya-lab/asya_lab/flow/parser.py:1054-1056` — rejects finally-only
- `src/asya-lab/asya_lab/flow/parser.py:1089` — rejects else

**What's needed**:
- `finally` block for cleanup actors (audit logging that always runs)
- Low priority — can use sequential actor after try/except as workaround
