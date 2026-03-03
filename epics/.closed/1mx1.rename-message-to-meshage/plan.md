# Execution Plan: Rename Message to Envelope

## Summary

Rename Asya's internal envelope type from "Message" to "Envelope" (mesh + message)
and rename the gateway's sidecar-facing routes from `/tasks/` to `/mesh/`.

## What Changes

| Symbol / Path | Before | After |
|---|---|---|
| Go package | `pkg/messages` | `pkg/envelopes` |
| Go file | `message.go` | `envelope.go` |
| Go struct | `messages.Message` | `envelopes.Envelope` |
| Gateway queue struct | `ActorMessage` | `ActorEnvelope` |
| Gateway queue struct | `ActorMessageStatus` | `ActorEnvelopeStatus` |
| Gateway func | `NewActorMessage` | `NewActorEnvelope` |
| Sidecar reporter struct | `CreateTaskPayload` | `CreateMeshPayload` |
| Sidecar reporter method | `CreateTask` | `CreateMesh` |
| Gateway sidecar routes | `/tasks/{id}/*` | `/mesh/{id}/*` |
| Gateway fanout route | `POST /tasks` | `POST /mesh` |
| Sidecar reporter URLs | `/tasks/%s/progress` etc. | `/mesh/%s/progress` etc. |
| Crew DLQ worker URLs | `/tasks/%s/final` | `/mesh/%s/final` |
| Gateway server URLs | `/tasks/%s` | `/mesh/%s` |
| Python runtime funcs | `_parse_message_json` | `_parse_envelope_json` |
| Python runtime funcs | `_validate_message` | `_validate_envelope` |
| Python runtime var | `message` | `envelope` |
| Python testing utils | `find_message_in_s3` | `find_envelope_in_s3` |
| Python testing utils | `wait_for_message_in_s3` | `wait_for_envelope_in_s3` |
| Python testing clients | `message` param | `envelope` param |
| Python testing class | `MessageHandler` | `EnvelopeHandler` |

## What Does NOT Change

- JSON wire field names (`id`, `route`, `payload`, `headers`, `status`) — no wire break
- A2A protocol types (`A2AMessage`, `/a2a/tasks/`) — external protocol
- AMQP/SQS `QueueMessage` — external transport concept
- Gateway `TaskStore` / `types.Task` — MCP task lifecycle, not envelope
- `StatusError.Message` field — error description string, not envelope type
- `ProgressUpdate.Message` field — human-readable text, not envelope type
- `TaskUpdate.Message` field — human-readable status text
- MCP/A2A endpoints (`/mcp`, `/a2a/`)
- `ASYA_MSG_ROOT` env var and `/proc/asya/msg/` VFS paths — separate concern (legacy VFS)
- `types.TaskStatus*` constants — the A2A RFC (1c0d) notes these may become
  `EnvelopeStatus` but defers that to the A2A native implementation, not 1mx1

---

## Phases

### Phase 1: Go core — package and struct rename

**Scope**: `src/asya-sidecar/pkg/messages/` → `src/asya-sidecar/pkg/envelopes/`

1. Rename directory: `pkg/messages/` → `pkg/envelopes/`
2. Rename file: `message.go` → `envelope.go`
3. Change package declaration: `package messages` → `package envelopes`
4. Rename struct: `Message` → `Envelope`
5. Update all comments referencing "message" in the envelope sense
6. Keep `StatusError.Message` field as-is (it's an error description string)

**Files**:
- `src/asya-sidecar/pkg/messages/message.go` → `src/asya-sidecar/pkg/envelopes/envelope.go`

### Phase 2: Go sidecar — update all imports and references

**Scope**: All files importing `pkg/messages`

1. Update import paths: `asya-sidecar/pkg/messages` → `asya-sidecar/pkg/envelopes`
2. Update type references: `messages.Message` → `envelopes.Envelope`
3. Update type references: `messages.Route` → `envelopes.Route`
4. Update type references: `messages.Status` → `envelopes.Status`
5. Update type references: `messages.StatusError` → `envelopes.StatusError`
6. Update type references: `messages.NewDefaultStatus` → `envelopes.NewDefaultStatus`
7. Update type references: `messages.Phase*` → `envelopes.Phase*`
8. Update type references: `messages.Reason*` → `envelopes.Reason*`
9. Update variable names in comments/logs where "message" means the envelope

**Files** (8 files):
- `src/asya-sidecar/internal/router/router.go`
- `src/asya-sidecar/internal/router/router_test.go`
- `src/asya-sidecar/internal/router/router_retry_test.go`
- `src/asya-sidecar/internal/router/router_on_error_test.go`
- `src/asya-sidecar/internal/runtime/client.go`
- `src/asya-sidecar/internal/runtime/client_test.go`
- `src/asya-sidecar/internal/progress/reporter.go`
- `src/asya-sidecar/internal/progress/reporter_test.go`

### Phase 3: Go sidecar — rename `/tasks/` URLs to `/mesh/`

**Scope**: Sidecar's gateway URL format strings

1. `reporter.go`: `"/tasks/%s/progress"` → `"/mesh/%s/progress"`
2. `reporter.go`: `"/tasks/%s/partial"` → `"/mesh/%s/partial"`
3. `reporter.go`: `"/tasks/%s/final"` → `"/mesh/%s/final"`
4. `reporter.go`: `"/tasks"` → `"/mesh"` (fanout creation)
5. `reporter.go`: `CreateTaskPayload` → `CreateMeshPayload`
6. `reporter.go`: `CreateTask` method → `CreateMesh`
7. `router.go`: `"/tasks/%s/final"` → `"/mesh/%s/final"` (two occurrences)
8. Update all test assertions for these URL paths

**Files**:
- `src/asya-sidecar/internal/progress/reporter.go`
- `src/asya-sidecar/internal/progress/reporter_test.go`
- `src/asya-sidecar/internal/router/router.go`
- `src/asya-sidecar/internal/router/router_test.go`

### Phase 4: Go gateway — rename internal routes `/tasks/` → `/mesh/`

**Scope**: Gateway route registrations and handler regex patterns

1. `cmd/gateway/main.go`: Change route registration from `"/tasks/"` to `"/mesh/"`
2. `cmd/gateway/main.go`: Change `"/tasks"` to `"/mesh"` (fanout creation)
3. `internal/mcp/handlers.go`: Rename all `taskPathRegex` → `meshPathRegex` etc.
4. `internal/mcp/handlers.go`: Update regex patterns from `^/tasks/` to `^/mesh/`
5. `internal/mcp/server.go`: Update `status_url` and `stream_url` from `/tasks/` to `/mesh/`
6. `internal/mcp/registry.go`: Same URL updates
7. Update all handler method names: `HandleTask*` → `HandleMesh*`
8. Update all test files with new paths and method names

**Files**:
- `src/asya-gateway/cmd/gateway/main.go`
- `src/asya-gateway/internal/mcp/handlers.go`
- `src/asya-gateway/internal/mcp/handlers_test.go`
- `src/asya-gateway/internal/mcp/server.go`
- `src/asya-gateway/internal/mcp/registry.go`
- `src/asya-gateway/internal/mcp/progress_tracking_test.go`

### Phase 5: Go gateway — rename ActorMessage types

**Scope**: Gateway queue package

1. `queue.go`: `ActorMessage` → `ActorEnvelope`
2. `queue.go`: `ActorMessageStatus` → `ActorEnvelopeStatus`
3. `queue.go`: `NewActorMessage` → `NewActorEnvelope`
4. Update all files using these types

**Files**:
- `src/asya-gateway/internal/queue/queue.go`
- `src/asya-gateway/internal/queue/queue_test.go`
- `src/asya-gateway/internal/queue/rabbitmq.go`
- `src/asya-gateway/internal/queue/rabbitmq_test.go`
- `src/asya-gateway/internal/queue/rabbitmq_pooled.go`
- `src/asya-gateway/internal/queue/sqs.go`

### Phase 6: Go crew — rename DLQ worker gateway URLs

**Scope**: Crew's DLQ worker gateway client

1. `gateway.go`: `"/tasks/%s/final"` → `"/mesh/%s/final"`
2. Update test assertions
3. Update README references

**Files**:
- `src/asya-crew/cmd/dlq-worker/gateway.go`
- `src/asya-crew/cmd/dlq-worker/gateway_test.go`
- `src/asya-crew/cmd/dlq-worker/README.md`
- `src/asya-crew/README.md`

### Phase 7: Go — build and test

1. `make build-go` — verify compilation
2. `make -C src/asya-sidecar test-unit` — sidecar unit tests
3. `make -C src/asya-gateway test-unit` — gateway unit tests

### Phase 8: Python runtime — rename internal references

**Scope**: `src/asya-runtime/asya_runtime.py`

1. `_parse_message_json` → `_parse_envelope_json`
2. `_validate_message` → `_validate_envelope`
3. `_get_current_actor(message)` → `_get_current_actor(envelope)` (param name)
4. `_collect_payload_frames(message, ...)` → `_collect_payload_frames(envelope, ...)`
5. `_handle_invoke` — update local variable `message` → `envelope`
6. `_stream_sse_response(self, message, ...)` → `_stream_sse_response(self, envelope, ...)`
7. `_AbiContext(message)` → `_AbiContext(envelope)` (param and internal refs)
8. Update all internal comments mentioning "message" in envelope sense
9. Keep: error strings like "Missing required field 'payload' in message" → update to "envelope"

**Files**:
- `src/asya-runtime/asya_runtime.py`

### Phase 9: Python runtime tests

**Scope**: `src/asya-runtime/tests/`

1. `_make_message()` → `_make_envelope()`
2. `TestMessageFieldPreservation` → `TestEnvelopeFieldPreservation`
3. Update variable names `message` → `envelope` in test functions
4. Update `call_invoke(message, ...)` → `call_invoke(envelope, ...)`

**Files**:
- `src/asya-runtime/tests/test_asya_runtime.py`

### Phase 10: Python testing library

**Scope**: `src/asya-testing/asya_testing/`

1. `clients/base.py`: `publish(queue, message)` → `publish(queue, envelope)`
2. `clients/rabbitmq.py`: Same parameter rename + log updates
3. `clients/sqs.py`: Same parameter rename + log updates
4. `utils/s3.py`: `find_message_in_s3` → `find_envelope_in_s3`
5. `utils/s3.py`: `wait_for_message_in_s3` → `wait_for_envelope_in_s3`
6. `handlers/classes.py`: `MessageHandler` → `EnvelopeHandler`
7. `handlers/fanout.py`: `_read_message_id()` → `_read_envelope_id()`

**Files**:
- `src/asya-testing/asya_testing/clients/base.py`
- `src/asya-testing/asya_testing/clients/rabbitmq.py`
- `src/asya-testing/asya_testing/clients/sqs.py`
- `src/asya-testing/asya_testing/utils/s3.py`
- `src/asya-testing/asya_testing/handlers/classes.py`
- `src/asya-testing/asya_testing/handlers/fanout.py`

### Phase 11: Python crew actors

**Scope**: `src/asya-crew/`

1. `pause.py`: Update comments/docstrings mentioning "message" in envelope sense
2. `fanin/s3_split_key.py`: `make_message()` → `make_envelope()`
3. Crew test files: update helper names and variable names

**Files**:
- `src/asya-crew/pause.py` (if references exist)
- `src/asya-crew/fanin/s3_split_key.py`
- `src/asya-crew/tests/fanin/test_s3_split_key.py`

### Phase 12: Python CLI / Flow DSL tests

**Scope**: `src/asya-cli/tests/flow/`

1. `_make_msg_ctx()` → keep as-is (abbreviation, not "message")
2. `make_message()` → `make_envelope()` in `test_while_integration.py`
3. Update comments mentioning "message routes" → "envelope routes"

**Files**:
- `src/asya-cli/tests/flow/test_try_except_integration.py`
- `src/asya-cli/tests/flow/test_fanout_codegen.py`
- `src/asya-cli/tests/flow/test_while_integration.py`

### Phase 13: Python — lint and test

1. `make -C src/asya-runtime test-unit`
2. `make -C src/asya-crew test-unit` (if applicable)
3. `make lint`

### Phase 14: Integration tests

**Scope**: `testing/integration/` and `testing/component/`

1. Update `publish_message` → `publish_envelope` in test conftest files
2. Update `get_message` → `get_envelope`
3. Update `wait_for_message` → `wait_for_envelope`
4. Update `wait_for_merged_result` (name may stay, check context)
5. Update inline message construction variable names
6. Update `/tasks/` URL references in any test assertions

**Files**:
- `testing/integration/fan-in/tests/conftest.py`
- `testing/integration/fan-in/tests/test_fanout_fanin.py`
- `testing/integration/sidecar-runtime/tests/conftest.py`
- Other integration test files referencing "message" in envelope sense

### Phase 15: Documentation

**Scope**: All docs mentioning the internal envelope

1. `AGENTS.md`: Update "Message Protocol" section, message flow description
2. `docs/architecture/protocols/actor-actor.md`: Rename "Message Structure" → "Envelope Structure"
3. `docs/architecture/protocols/sidecar-runtime.md`: Update POST /invoke references
4. `docs/concepts.md`: Update "Message" section → "Envelope"
5. `docs/architecture/asya-gateway.md`: Update `/tasks/` endpoint references
6. `docs/reference/abi-protocol.md`: Update message metadata references
7. `src/asya-gateway/README.md`: Update route table

**Files**:
- `AGENTS.md`
- `docs/architecture/protocols/actor-actor.md`
- `docs/architecture/protocols/sidecar-runtime.md`
- `docs/concepts.md`
- `docs/architecture/asya-gateway.md`
- `docs/reference/abi-protocol.md`
- `src/asya-gateway/README.md`
- `src/asya-crew/cmd/dlq-worker/README.md`
- `src/asya-crew/README.md`

### Phase 16: Final verification

1. `make build` — all components compile
2. `make test-unit` — all unit tests pass
3. `make lint` — no lint errors
4. Full grep for stale references: `rg -w "messages\.Message" src/`
5. Full grep for stale `/tasks/` internal routes (excluding A2A)

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Sidecar ↔ Gateway version skew | Both change atomically in same commit; deployed together |
| Integration/E2E tests break | URL changes propagate to test assertions |
| Go import cycle after rename | Mechanical rename, same dependency graph |
| Python runtime symlink | Symlink follows source; no manual sync needed |
| `StatusError.Message` accidentally renamed | Excluded explicitly — it's a string field, not the type |

## Verified Against A2A RFC (1c0d/rfc-a2a-native.md)

This plan was cross-checked against the A2A native protocol RFC. Findings:

1. **Route rename is a prereq for A2A** — RFC Phase 1 (Section 14) explicitly
   lists "Rename `/tasks/*` to `/mesh/*` (Epic 1mx1)" as a dependency. The RFC's
   endpoint map (Section 6.1) already uses `/mesh/*` for sidecar routes and
   reserves `/tasks/*` (under configurable prefix) for A2A client-facing routes.

2. **No collision with A2A `/tasks/` routes** — A2A uses
   `{prefix}/tasks/{id}` (e.g. `/a2a/tasks/{id}`) while internal mesh routes
   live at `/mesh/{id}/*`. The RFC explicitly notes this (Section 6.1, line 497):
   "Collision avoidance: internal sidecar-facing routes are at `/mesh/*`".

3. **`TaskStatus` rename deferred** — RFC line 185 notes `TaskStatus` should
   become `EnvelopeStatus`, but the RFC's own code examples still use
   `types.TaskStatus*` constants. This rename belongs to the A2A implementation
   (1c0d), not to 1mx1, since it involves restructuring the gateway type system
   around `a2a-go` library types.

4. **`types.Task` stays** — The RFC continues to use `types.Task` as the
   gateway's internal task representation (Section 6.3, line 560). The A2A RFC
   wraps it with `A2AStoreAdapter`. No conflict with our decision to keep
   `TaskStore` and `types.Task` unchanged.

5. **`CreateTaskPayload` / `CreateTask` → added** — The RFC references
   `POST /mesh` for fanout child creation. Plan updated to include the method
   and struct rename (`CreateMesh`, `CreateMeshPayload`).

## Execution Strategy

- Use `sed`/editor find-and-replace for mechanical renames within each phase
- Compile after Go phases (1-6) before proceeding to Python
- Run unit tests after each language boundary
- Commit per logical phase (or batch closely related phases)
