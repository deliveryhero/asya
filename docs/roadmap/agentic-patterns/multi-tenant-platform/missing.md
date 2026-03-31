# Multi-Tenant Platform: Missing Functionality

## P0 — Blocking

### 1. No per-namespace flow isolation in gateway

**Current state**: Gateway serves all flows from a single ConfigMap directory.
All MCP tools and A2A skills are visible to all authenticated clients.

**Files**:
- `src/asya-gateway/internal/toolstore/registry.go` — `LoadFromDir()` reads
  all YAML files from one directory
- `src/asya-gateway/internal/mcp/handlers.go` — no namespace filtering

**What's needed**:
- Namespace-scoped tool registries (Team A sees only its tools)
- Per-namespace API keys or OAuth scopes
- Tool-level authorization in gateway middleware

**Workaround**: Deploy one gateway per namespace (heavy, but works today).

### 2. No scope-based tool filtering (OAuth)

**Current state**: OAuth 2.1 is fully implemented but tokens include scope
field that is never validated on tool calls. All authenticated clients can
call all tools.

**Files**:
- `src/asya-gateway/internal/oauth/server.go` — scope stored but not enforced
- `src/asya-gateway/internal/mcp/handlers.go` — no scope check before dispatch

**What's needed**:
- Scope validation middleware: `tools:team-a:*` restricts to Team A's tools
- Scope-filtered `tools/list` responses

---

## P1 — Important

### 3. No resource quotas per team in gateway

**Current state**: Gateway has no rate limiting, request quotas, or
concurrency caps per client/team. A runaway client can exhaust gateway
resources.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go` — no rate limiting
- `src/asya-gateway/internal/a2a/executor.go` — no concurrency limits

**What's needed**:
- Per-client rate limiting (token bucket or sliding window)
- Configurable concurrency caps per tool/flow
- Queue depth limits per team namespace

### 4. No flow-level metrics isolation

**Current state**: Gateway emits metrics but not segmented by team/namespace.
Platform team can't show per-team usage dashboards.

**What's needed**:
- Labels on Prometheus metrics: `team`, `namespace`, `flow_name`
- Per-team cost attribution (LLM token counts, compute time)

---

## P2 — Nice to Have

### 5. No self-service flow deployment

**Current state**: Deploying a new flow requires `kubectl apply` of CRDs +
updating gateway ConfigMap. Teams can't self-serve.

**What's needed**:
- CLI command: `asya flow deploy <flow.py> --namespace team-a`
- Automated CRD generation + ConfigMap update
- Validation webhook to prevent cross-namespace resource access
