# Testing: A2A Protocol

How the A2A (Agent-to-Agent) protocol implementation in `asya-gateway` is tested
across all levels: unit, integration, and end-to-end.

## Support Matrix

| Feature | Unit | Integration | E2E |
|---------|------|-------------|-----|
| Auth: API key | ✅ `auth_test.go` | — | ✅ `test_a2a_e2e.py` |
| Auth: JWT Bearer (RS256) | ✅ `auth_test.go` | — | ✅ `test_a2a_e2e.py` |
| Auth: JWT expired | ✅ | — | ✅ |
| Auth: wrong issuer / audience | ✅ | — | ✅ |
| Agent card (`/.well-known/agent.json`) | ✅ `agent_card_producer_test.go` | — | ✅ |
| Extended agent card (skills from DB) | ✅ | — | ✅ |
| `tasks/send` (blocking SSE) | ✅ `blocking_test.go` | ✅ `gateway-actors` | ✅ |
| `tasks/get` | ✅ `executor_test.go` | ✅ | ✅ |
| `tasks/subscribe` (live SSE) | ✅ | ✅ | ✅ |
| `tasks/cancel` | ✅ | ✅ | ✅ |
| `tasks/list` | ✅ | ✅ | ✅ |
| A2A→envelope translation | ✅ `translator_test.go` | — | — |
| FLY frame→SSE streaming | ✅ `fly_test.go` | ✅ | ✅ |
| State machine transitions | ✅ `state_test.go` | — | — |
| Multi-hop pipeline | — | ✅ | ✅ |
| `a2a_enabled` DB flag (tool registry) | ✅ `store_adapter_test.go` | ✅ | ✅ |

## Unit Tests

**Location**: `src/asya-gateway/internal/a2a/`

Each A2A subsystem has its own test file with no external dependencies.

### Auth (`auth_test.go`)

Tests the `Authenticator` that wraps the A2A JSON-RPC handler and rejects
unauthenticated or malformed credentials before dispatch.

| Scenario | Assertion |
|----------|-----------|
| No credentials | HTTP 401 + JSON-RPC error code `-32005` |
| Valid `X-API-Key` header | Request passes through to handler |
| Wrong API key | HTTP 401 |
| Valid `Authorization: Bearer <RS256 JWT>` | Passes through |
| Expired JWT | HTTP 401 |
| JWT wrong issuer | HTTP 401 |
| JWT wrong audience | HTTP 401 |
| JWT wrong algorithm (HS256) | HTTP 401 |
| JWKS URL unavailable at startup | Gateway starts, JWT auth disabled gracefully |

**JWKS in tests**: Tests use a locally generated RSA key pair and a
`httptest.Server` serving the JWKS document — no external HTTP involved.

### Executor (`executor_test.go`)

Tests the JSON-RPC dispatcher that routes methods to handlers.

| Method | Scenario | Assertion |
|--------|----------|-----------|
| `tasks/send` | Valid payload | Dispatches to blocking handler |
| `tasks/get` | Known task ID | Returns task with current state |
| `tasks/get` | Unknown task ID | JSON-RPC error `-32001` (not found) |
| `tasks/list` | Context ID with tasks | Returns task list |
| `tasks/list` | Unknown context ID | Returns empty list |
| `tasks/cancel` | Running task | Returns `canceled` state |
| `tasks/subscribe` | Completed task | Immediate final event |
| Unknown method | Any | JSON-RPC error `-32601` |
| Malformed JSON | Any | JSON-RPC error `-32700` |

### Blocking (`blocking_test.go`)

Tests the SSE streaming loop that holds the HTTP connection open until a task
reaches terminal state.

| Scenario | Assertion |
|----------|-----------|
| Task completes quickly | Stream ends with `final=true`, state=`completed` |
| Task fails | Stream ends with `final=true`, state=`failed` |
| Task canceled externally | Stream ends with `final=true`, state=`canceled` |
| Client disconnects mid-stream | Goroutine exits without panic or leak |
| Multiple FLY events in-flight | All events forwarded before final |

### State Machine (`state_test.go`)

Tests valid and invalid A2A task state transitions.

| Transition | Valid |
|------------|-------|
| `submitted` → `working` | ✅ |
| `working` → `completed` | ✅ |
| `working` → `failed` | ✅ |
| `working` → `canceled` | ✅ |
| `completed` → `working` | ❌ (illegal) |
| `canceled` → `completed` | ❌ (illegal) |

### Translator (`translator_test.go`)

Tests conversion between A2A `Message` parts and asya envelope `payload`.

| Input | Expected output |
|-------|----------------|
| Single `data` part | `payload` = part's data object |
| Multiple `data` parts | `payload` = merged object |
| `text` part | `payload.text` = text content |
| Missing parts | JSON-RPC error `-32602` (invalid params) |
| Skill hint in `metadata` | Tool name resolved from DB |

### FLY Streaming (`fly_test.go`)

Tests forwarding of ABI `FLY` frames from the actor mesh to the SSE stream.

| Scenario | Assertion |
|----------|-----------|
| `FLY` frame with `type=text_delta` | Forwarded as SSE event before final |
| `FLY` frame with custom fields | Forwarded verbatim |
| No `FLY` frames | Only status events in stream |

### Store Adapter (`store_adapter_test.go`)

Tests the bridge between the A2A layer and the task store (PostgreSQL).

| Scenario | Assertion |
|----------|-----------|
| `a2a_enabled=true` tool | Resolved by skill name |
| `a2a_enabled=false` tool | Returns "tool not found for A2A" error |
| Unknown skill name | Returns not-found error |

**Run**: `make -C src/asya-gateway test-unit`

---

## Integration Tests

**Location**: `testing/integration/gateway-actors/`

Tests the gateway talking to real actors over a message transport (SQS or
RabbitMQ) inside Docker Compose. No Kind cluster required.

### A2A Integration Scenarios

| Scenario | Profile | Assertion |
|----------|---------|-----------|
| `tasks/send` → echo actor → `completed` | rabbitmq, sqs | Final SSE state=`completed` |
| `tasks/get` after completion | rabbitmq | Non-empty task struct |
| `tasks/list` with context | rabbitmq | At least one task returned |
| `tasks/cancel` while running | rabbitmq | State transitions to `canceled` |
| `tasks/subscribe` live stream | rabbitmq | Events arrive before task finishes |
| Multi-hop pipeline (doubler→incrementer) | rabbitmq | Final payload transformed correctly |

**Infrastructure**: The A2A tests use `ASYA_A2A_API_KEY=test-key` (set in the
Docker Compose environment) and a gateway configured without JWT (JWKS URL
unset), so only API key auth is exercised at integration level.

**Run**: `make -C testing/integration/gateway-actors test`

---

## E2E Tests

**Location**: `testing/e2e/tests/test_a2a_e2e.py`

Full K8s stack (Kind cluster) with real JWKS infrastructure.

### Infrastructure Setup

```
deploy.sh Phase 4:
  1. generate_jwks.py → .jwks/private_key.pem + .jwks/jwks.json
  2. kubectl create secret jwks-keys (contains both jwks.json + private_key.pem)

deploy.sh Phase 5 (helmfile layer=infra):
  3. jwks-server Deployment:
       - init container (asya-testing:latest): copies jwks.json from Secret → EmptyDir
       - main container (asya-testing:latest): python3 -m http.server 8080
       - Service port 80 → container port 8080
  4. asya-gateway Deployment with env:
       ASYA_A2A_API_KEY=test-api-key-e2e
       ASYA_A2A_JWT_JWKS_URL=http://asya-jwks-server.asya-e2e.svc.cluster.local/jwks.json
       ASYA_A2A_JWT_ISSUER=https://test-issuer.e2e
       ASYA_A2A_JWT_AUDIENCE=asya-gateway-e2e
```

Host-side pytest reads the private key from `.jwks/private_key.pem` to sign
JWTs in JWT-specific tests (loaded lazily; JWT tests skip if key absent).

Note: The `asya-testing` image is used for both the init container and the
server — it is pre-loaded into Kind by `deploy.sh` Phase 3, so no Docker Hub
pull is needed (avoids rate limits).

### A2A-Enabled Tools (values.yaml)

Three tools are configured with `a2a: enabled: true` so they appear as skills
in the agent card and can be dispatched via `metadata.skill`:

| Tool | Skill name | Route |
|------|-----------|-------|
| `test_echo` | `test_echo` | `[test-echo]` |
| `test_pipeline` | `test_pipeline` | `[test-doubler, test-incrementer]` |
| `test_slow_boundary` | `test_slow_boundary` | `[test-slow-boundary]` |

### Test Scenarios

#### Agent Card (public, no auth required)

| Test | Assertion |
|------|-----------|
| `test_agent_card_is_public` | HTTP 200, `name` + `capabilities` fields present |
| `test_agent_card_capabilities` | `capabilities.streaming == true` |
| `test_extended_agent_card_has_skills` | At least one skill with `a2a_enabled=true` |

#### Authentication

| Test | Auth | Expected |
|------|------|----------|
| `test_a2a_no_auth_returns_401` | None | 401 + JSON-RPC `-32005` |
| `test_a2a_valid_api_key_passes` | `X-API-Key: test-api-key-e2e` | Not 401 |
| `test_a2a_wrong_api_key_returns_401` | `X-API-Key: wrong` | 401 |
| `test_a2a_valid_jwt_passes` | `Bearer <valid RS256>` | Not 401 |
| `test_a2a_expired_jwt_returns_401` | `Bearer <expired RS256>` | 401 |
| `test_a2a_wrong_issuer_returns_401` | `Bearer <wrong iss>` | 401 |
| `test_a2a_wrong_audience_returns_401` | `Bearer <wrong aud>` | 401 |

#### Protocol Methods

| Test | Method | Assertion |
|------|--------|-----------|
| `test_tasks_send_dispatches_work_and_returns_task_state` | `tasks/send` | SSE stream ends with `final=true`, state=`completed` |
| `test_tasks_get_returns_task_state` | `tasks/get` | State=`completed` for known task |
| `test_tasks_subscribe_streams_events` | `tasks/subscribe` | Events received, final state=`completed` |
| `test_tasks_subscribe_live_stream` | `tasks/subscribe` | Events arrive while task is running |
| `test_tasks_cancel_transitions_to_cancelled` | `tasks/cancel` | State=`canceled` |
| `test_tasks_list_returns_tasks_for_context` | `tasks/list` | ≥2 tasks for shared context ID |
| `test_multihop_pipeline_via_a2a` | `tasks/send` | Multi-actor pipeline reaches `completed` |

### Helper Functions

```python
_send_task(skill, payload) -> list[dict]
    # tasks/send with metadata.skill; collects SSE until result.final=True

_a2a_stream(method, params) -> list[dict]
    # Generic SSE collector

_a2a_post(method, params) -> dict
    # Non-streaming JSON-RPC call

_final_state(events) -> str
    # Extract last status.state from event list

_make_jwt(private_key, *, expired, wrong_issuer, wrong_audience) -> str
    # Sign RS256 JWT for auth tests
```

### Running

```bash
# Full deploy + test
make test PROFILE=rabbitmq-minio

# Tests only (cluster already up)
make trigger-tests PROFILE=rabbitmq-minio

# Specific A2A tests only
make trigger-tests PROFILE=rabbitmq-minio PYTEST_OPTS="-v -s -k test_a2a"
```

---

## Coverage Gaps and Rationale

| Scenario | Level absent | Rationale |
|----------|-------------|-----------|
| JWT auth | Integration | JWKS requires a running HTTP server; Docker Compose can serve it but adds complexity. API-key auth suffices at integration level. |
| Concurrent `tasks/send` (fan-out) | E2E | Already covered by MCP fan-out tests (`test_fanout_fanin_flow_e2e.py`). |
| `tasks/send` with `text` message parts | Unit only | Actor mesh only sees `payload`; text→payload translation is a unit concern. |
| A2A over Pub/Sub transport | E2E only | Integration test matrix does not include Pub/Sub; covered by `pubsub-gcs` E2E profile. |
