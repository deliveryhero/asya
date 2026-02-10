# Yield-Only Fan-Out Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove list-return fan-out from the runtime, replace with yield/generator-based fan-out exclusively.

**Architecture:** The runtime currently uses `isinstance(payload, (list, tuple))` to detect fan-out — if a handler returns a list, each element becomes a separate output message. This creates type ambiguity (is a list a payload or fan-out?). The new model: `return` always produces ONE message, `yield` produces one message per yield. The wire protocol (JSON array over Unix socket) stays unchanged — only how the runtime populates that array changes. The sidecar requires no changes.

**Tech Stack:** Python (asya-runtime), Python (asya-testing handlers), Go (sidecar — read-only verification), pytest, go test

**Bead:** asya-51j1

---

## New Handler Model

```
+------------------+----------------------------+-------------------------------+
| Handler Type     | Signature                  | Behavior                      |
+------------------+----------------------------+-------------------------------+
| sync return      | def h(p) -> dict           | ONE output message            |
| async return     | async def h(p) -> dict     | ONE output message (future)   |
| sync yield       | def h(p) -> Generator      | One message per yield         |
| async yield      | async def h(p) -> AsyncGen | One message per yield (future)|
+------------------+----------------------------+-------------------------------+
```

- `return None` = no output, sidecar routes to happy-end (abort)
- `return <value>` = one output (even if value is a list — the list IS the payload)
- `yield <value>` = one output per yield (must yield at least once)
- async variants are out of scope for this bead (agentic compiler RFC Phase 3)

## Wire Protocol: NO CHANGE

The runtime still sends `json.dumps(out_list)` (a JSON array) over the Unix socket.
The sidecar still reads `[]RuntimeResponse`. No sidecar code changes needed.

What changes is only how `out_list` is populated inside the runtime:
- **Before**: `isinstance(result, list)` → unwrap into multiple array elements
- **After**: `return` → always `[{single_response}]`, generator → `[{yield1}, {yield2}, ...]`

---

### Task 1: Runtime — Remove list-return sniffing in payload mode

**Files:**
- Modify: `src/asya-runtime/asya_runtime.py:414-433`
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write failing test — list return is treated as single payload, not fan-out**

Add test to `TestHandleRequestPayloadMode`:

```python
def test_handle_request_list_return_is_single_payload(self, socket_pair, mock_env):
    """A handler returning a list should produce ONE response with the list AS the payload."""
    server_sock, client_sock = socket_pair

    def list_handler(payload):
        return [{"a": 1}, {"b": 2}, {"c": 3}]

    request = {
        "payload": {"test": "list_return"},
        "route": {"actors": ["me"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, list_handler)

    assert len(responses) == 1  # ONE response, not three
    assert responses[0]["payload"] == [{"a": 1}, {"b": 2}, {"c": 3}]
    assert responses[0]["route"]["current"] == 1
```

**Step 2: Run test to verify it fails**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_list_return_is_single_payload"
```
Expected: FAIL — currently produces 3 responses instead of 1.

**Step 3: Modify payload mode to remove isinstance check**

In `src/asya-runtime/asya_runtime.py`, replace lines 414-433:

```python
        if ASYA_HANDLER_MODE == "payload":
            logger.info(f"[DIAG] Calling user_func with payload: {message['payload']}")

            if inspect.isgeneratorfunction(user_func):
                result_iter = user_func(message["payload"])
            else:
                result = user_func(message["payload"])
                result_iter = iter([result]) if result is not None else iter([])

            logger.info(f"[DIAG] user_func returned (generator={inspect.isgeneratorfunction(user_func)})")

            # Build output route with incremented current
            output_route = message["route"].copy()
            output_route["current"] = message["route"]["current"] + 1

            out_list = []
            for p in result_iter:
                out: dict[str, Any] = {"payload": p, "route": output_route}
                if "headers" in message:
                    out["headers"] = message["headers"]
                out_list.append(out)
```

**Step 4: Run test to verify it passes**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_list_return_is_single_payload"
```
Expected: PASS

**Step 5: Run all existing payload mode tests to check what breaks**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k TestHandleRequestPayloadMode"
```
Expected: Some fan-out tests will fail (they rely on list-return). We fix those in Task 4.

**Step 6: Commit**

```bash
git add src/asya-runtime/asya_runtime.py src/asya-runtime/tests/test_asya_runtime.py
git commit -m "feat(runtime): remove list-return fan-out in payload mode

return value is always treated as a single payload.
A returned list IS the payload, not fan-out.
Adds generator detection for yield-based fan-out."
```

---

### Task 2: Runtime — Remove list-return sniffing in envelope mode

**Files:**
- Modify: `src/asya-runtime/asya_runtime.py:435-457`
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write failing test — list return in envelope mode is single response**

Add test to `TestHandleRequestEnvelopeMode`:

```python
def test_handle_request_list_return_is_single_response(self, socket_pair, mock_env_envelope):
    """A handler returning a list in envelope mode should produce ONE response."""
    server_sock, client_sock = socket_pair

    def list_envelope_handler(envelope):
        route = envelope["route"].copy()
        route["current"] += 1
        return {
            "payload": [{"a": 1}, {"b": 2}],  # List IS the payload
            "route": route,
        }

    request = {
        "payload": {"test": "list_return"},
        "route": {"actors": ["me", "next"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, list_envelope_handler)

    assert len(responses) == 1
    assert responses[0]["payload"] == [{"a": 1}, {"b": 2}]
```

**Step 2: Run test to verify it fails**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_list_return_is_single_response"
```

**Step 3: Modify envelope mode to remove isinstance check**

Replace lines 435-457 in `asya_runtime.py`:

```python
        elif ASYA_HANDLER_MODE == "envelope":
            if inspect.isgeneratorfunction(user_func):
                result_iter = user_func(message)
            else:
                result = user_func(message)
                result_iter = iter([result]) if result is not None else iter([])

            out_list = list(result_iter)

            # Output validation (only when enabled)
            if ASYA_ENABLE_VALIDATION:
                for i, out in enumerate(out_list):
                    try:
                        out_list[i] = _validate_message(
                            out,
                            expected_current_actor=_get_current_actor(message),
                            input_route=message["route"],
                        )
                    except ValueError as exc:
                        raise ValueError(f"Invalid output message[{i}/{len(out_list)}]: {exc}") from exc
```

**Step 4: Run test to verify it passes**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_list_return_is_single_response"
```

**Step 5: Commit**

```bash
git add src/asya-runtime/asya_runtime.py src/asya-runtime/tests/test_asya_runtime.py
git commit -m "feat(runtime): remove list-return fan-out in envelope mode

Same treatment as payload mode — return value is always single response.
Generator detection added for yield-based fan-out."
```

---

### Task 3: Runtime — Add sync generator fan-out tests (payload mode)

**Files:**
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write test for generator fan-out in payload mode**

```python
def test_handle_request_generator_fanout(self, socket_pair, mock_env):
    """A generator handler yielding 3 items should produce 3 responses."""
    server_sock, client_sock = socket_pair

    def generator_handler(payload):
        count = payload.get("count", 3)
        for i in range(count):
            yield {**payload, "index": i, "message": f"Fan-out message {i}"}

    request = {
        "payload": {"test": "generator", "count": 3},
        "route": {"actors": ["gen"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, generator_handler)

    assert len(responses) == 3
    for i, resp in enumerate(responses):
        assert resp["payload"]["index"] == i
        assert resp["payload"]["message"] == f"Fan-out message {i}"
        assert resp["route"]["current"] == 1  # Auto-incremented
```

**Step 2: Run test to verify it passes (should pass from Task 1 changes)**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_generator_fanout"
```
Expected: PASS (generator detection was added in Task 1).

**Step 3: Write test for single-yield generator**

```python
def test_handle_request_generator_single_yield(self, socket_pair, mock_env):
    """A generator yielding once should produce 1 response."""
    server_sock, client_sock = socket_pair

    def single_yield_handler(payload):
        yield {**payload, "yielded": True}

    request = {
        "payload": {"test": "single_yield"},
        "route": {"actors": ["gen"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, single_yield_handler)

    assert len(responses) == 1
    assert responses[0]["payload"]["yielded"] is True
```

**Step 4: Write test for headers preserved in generator fan-out**

```python
def test_handle_request_generator_preserves_headers(self, socket_pair, mock_env):
    """Headers should be preserved across all yielded responses."""
    server_sock, client_sock = socket_pair

    def gen_handler(payload):
        yield {"index": 0}
        yield {"index": 1}

    request = {
        "payload": {},
        "route": {"actors": ["gen"], "current": 0},
        "headers": {"trace_id": "abc-123"},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, gen_handler)

    assert len(responses) == 2
    for resp in responses:
        assert resp["headers"]["trace_id"] == "abc-123"
```

**Step 5: Run all new generator tests**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k 'generator'"
```

**Step 6: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): add generator fan-out tests for payload mode"
```

---

### Task 4: Runtime — Add sync generator fan-out tests (envelope mode)

**Files:**
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write test for generator fan-out in envelope mode**

```python
def test_handle_request_generator_fanout_envelope(self, socket_pair, mock_env_envelope):
    """A generator handler in envelope mode yielding multiple envelopes."""
    server_sock, client_sock = socket_pair

    def gen_envelope_handler(envelope):
        route = envelope["route"].copy()
        route["current"] += 1
        for i in range(3):
            yield {
                "payload": {"index": i},
                "route": route,
            }

    request = {
        "payload": {},
        "route": {"actors": ["me", "next"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    responses = handle_and_receive(server_sock, client_sock, gen_envelope_handler)

    assert len(responses) == 3
    for i, resp in enumerate(responses):
        assert resp["payload"]["index"] == i
        assert resp["route"]["current"] == 1
```

**Step 2: Run and verify passes**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_handle_request_generator_fanout_envelope"
```

**Step 3: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): add generator fan-out tests for envelope mode"
```

---

### Task 5: Fix broken existing tests

The following existing tests relied on list-return fan-out and will now fail. They need to be rewritten to either (a) use generators or (b) test that list return is treated as single payload.

**Files:**
- Modify: `src/asya-runtime/tests/test_asya_runtime.py`

**Tests to update (found from exploration):**

| Test | Class | Line | Fix |
|------|-------|------|-----|
| `test_handle_request_fanout_list_output` | `TestHandleRequestPayloadMode` | ~1057 | Rewrite: use generator handler |
| `test_handle_request_fanout_list_output` | `TestHandleRequestEnvelopeMode` | ~1135 | Rewrite: use generator handler |
| `test_handler_returns_empty_list` | `TestHandlerReturnTypeValidation` | ~147 | Rewrite: `return []` is now a payload, not abort |
| `test_handler_fanout_with_actor_validation` | (implicit) | ~465 | Rewrite: use generator handler |
| `test_handler_fanout_with_invalid_actor_name` | (implicit) | ~502 | Rewrite: use generator handler |
| `test_class_handler_fanout_payload_mode` | `TestClassBasedHandlers` | ~1545 | Rewrite: use generator class method |
| `test_headers_preserved_in_fanout_payload_mode` | `TestHeadersPreservation` | ~2022 | Rewrite: use generator handler |
| `test_envelope_mode_fanout` | `TestEnvelopeMode` | ~2165 | Rewrite: use generator handler |
| `test_envelope_mode_returns_none` | `TestEnvelopeMode` | ~2221 | Keep as-is (None still means abort) |

**Step 1: Read each failing test, rewrite to use generators**

For each test that creates a handler returning a list, convert to a generator:

```python
# BEFORE: list-return fan-out
def fanout_handler(payload):
    return [{"index": i} for i in range(3)]

# AFTER: generator fan-out
def fanout_handler(payload):
    for i in range(3):
        yield {"index": i}
```

For `test_handler_returns_empty_list`: the test asserted that `return []` produces 0 responses. Now `return []` produces 1 response with `[]` as payload. Update assertion:

```python
def test_handler_returns_empty_list(self, ...):
    def empty_list_handler(payload):
        return []

    # ... send request ...
    responses = handle_and_receive(...)
    assert len(responses) == 1  # One response, payload is empty list
    assert responses[0]["payload"] == []
```

**Step 2: Run full test suite to verify all pass**

```bash
make -C src/asya-runtime test-unit
```

**Step 3: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): rewrite fan-out tests to use generators

All fan-out tests now use yield instead of list return.
Tests for list return verify it's treated as single payload."
```

---

### Task 6: Update test handlers in asya-testing

**Files:**
- Modify: `src/asya-testing/asya_testing/handlers/payload.py:117-145,278-300`

**Step 1: Convert fanout_handler to generator**

```python
def fanout_handler(payload: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """
    Fan-out handler: Yields multiple results.

    Tests that sidecar properly handles generator responses and routes
    each result to the next actor.
    """
    count = payload.get("count", 3)

    for i in range(count):
        yield {**payload, "index": i, "message": f"Fan-out message {i}"}
```

**Step 2: Update empty_response_handler**

```python
def empty_response_handler(payload: dict[str, Any]) -> None:
    """
    Empty response handler: Returns None to abort pipeline.

    This should send the original message to happy-end queue.
    """
    return None
```

**Step 3: Update none_response_handler**

```python
def none_response_handler(payload: dict[str, Any]) -> None:
    """
    None response handler: Returns None to abort pipeline.

    This should send the original message to happy-end queue.
    """
    return None
```

**Step 4: Update conditional_handler — remove "fanout" action**

The `conditional_handler` can't have a "fanout" action anymore because adding `yield` to any code path makes the entire function a generator. Create a separate `conditional_fanout_handler` generator:

```python
def conditional_handler(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Conditional handler: Behavior based on payload content.

    Supports actions: success, error, oom, slow, empty
    Note: 'fanout' action moved to conditional_fanout_handler (generator).
    """
    action = payload.get("action", "success")

    if action == "error":
        raise ValueError(f"Conditional error: {payload.get('error_msg', 'test')}")
    elif action == "oom":
        raise MemoryError("Conditional OOM")
    elif action == "slow":
        time.sleep(payload.get("sleep", 2))  # Simulate slow processing for testing
        return {**payload, "status": "slow_processing_complete"}
    elif action == "empty":
        return None
    else:
        return {**payload, "status": "success", "action": action}


def conditional_fanout_handler(payload: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """
    Conditional fan-out handler: Yields multiple results.

    Separated from conditional_handler because Python generators
    cannot mix return-with-value and yield in the same function.
    """
    count = payload.get("count", 2)
    for i in range(count):
        yield {"index": i, "action": "fanout"}
```

**Step 5: Add `Generator` import**

Add to the imports at the top of `payload.py`:

```python
from collections.abc import Generator
```

**Step 6: Commit**

```bash
git add src/asya-testing/asya_testing/handlers/payload.py
git commit -m "feat(testing): convert fan-out handlers to generators

fanout_handler now uses yield instead of returning list.
conditional_handler 'fanout' action moved to separate generator.
empty/none response handlers simplified to return None."
```

---

### Task 7: Verify sidecar tests still pass (no changes needed)

**Files:**
- Read-only: `src/asya-sidecar/internal/router/router_test.go`
- Read-only: `src/asya-sidecar/internal/runtime/client.go`

The sidecar reads `[]RuntimeResponse` from the wire. The runtime still sends JSON arrays. The sidecar fan-out ID logic (`{id}-{index}`, `parentID`) still works identically for generator-produced arrays.

**Step 1: Run sidecar unit tests**

```bash
make -C src/asya-sidecar test-unit
```
Expected: ALL PASS (no sidecar code changed).

**Step 2: If any fail, investigate**

The sidecar tests mock the runtime response directly as `[]RuntimeResponse`. They should be unaffected.

---

### Task 8: Update integration tests

**Files:**
- Modify: `testing/integration/sidecar-runtime/tests/test_sidecar_with_runtime.py:358-376`

**Step 1: Verify test_fanout uses the updated fanout_handler**

The integration test `test_fanout` (line 358) uses the `fanout_handler` from `asya_testing.handlers.payload`. Since we converted it to a generator in Task 6, the test should still work — the runtime will detect the generator and iterate it.

**Step 2: Run integration tests**

```bash
make -C testing/integration/sidecar-runtime test
```

**Step 3: If test_fanout fails, debug**

Check:
- Does the runtime correctly detect the generator handler loaded via `ASYA_HANDLER`?
- The runtime calls `_load_function()` which returns the function object. `inspect.isgeneratorfunction()` should detect it.
- For class methods that are generators, `inspect.isgeneratorfunction(bound_method)` also works.

**Step 4: Commit (if any test changes needed)**

```bash
git add testing/integration/sidecar-runtime/
git commit -m "fix(integration): update fan-out test for generator handlers"
```

---

### Task 9: Update documentation

**Files:**
- Modify: `docs/architecture/protocols/actor-actor.md:86-114`
- Modify: `src/asya-runtime/README.md:195-202`
- Modify: `src/asya-sidecar/README.md:43-48`
- Modify: `src/asya-sidecar/pkg/messages/message.go:12-24`

**Step 1: Update actor-actor.md — replace Fan-Out (Array) section**

Replace lines 86-109:

```markdown
### Fan-Out (Generator/Yield)

Runtime handler uses `yield` to produce multiple outputs:
```python
def process(payload):
    for item in payload["items"]:
        yield {"processed": item}
```

**Action**: Sidecar creates multiple messages (one per yield) -> Routes to next actor

**Fanout ID semantics**:

- First message retains original ID (for SSE streaming compatibility)
- Subsequent messages receive suffixed IDs: `{original_id}-{index}`
- All fanout children have `parent_id` set to original message ID

**Example**: Message `abc-123` yields 3 items:

- Index 0: `id="abc-123"`, `parent_id=null` (original ID preserved)
- Index 1: `id="abc-123-1"`, `parent_id="abc-123"` (fanout child)
- Index 2: `id="abc-123-2"`, `parent_id="abc-123"` (fanout child)

**Note**: Returning a list from a handler does NOT trigger fan-out.
The list is treated as a single payload value.
```

**Step 2: Update actor-actor.md — Empty Response section**

Replace lines 110-114 with:

```markdown
### Empty Response

Runtime returns `None`:

**Action**: Sidecar routes message to `happy-end` (no increment)
```

**Step 3: Update runtime README fan-out example**

Replace the fan-out example in `src/asya-runtime/README.md`:

```python
# Fan-out (yield):
def process(payload):
    for item in payload["items"]:
        yield {"processed": item}
```

**Step 4: Update sidecar README response handling**

Replace array fan-out line in `src/asya-sidecar/README.md`:

```
- Single value: {"processed": true, "data": "..."}
- Generator (fan-out): multiple responses via yield
- Empty: null (handler returns None)
```

**Step 5: Update message.go fan-out doc comment**

Update the comment at `src/asya-sidecar/pkg/messages/message.go:14-15`:

```go
// Fanout ID Semantics:
// When an actor handler uses yield (generator), the runtime produces multiple responses.
// The sidecar creates multiple messages (fanout), one per yielded response.
```

**Step 6: Commit**

```bash
git add docs/architecture/protocols/actor-actor.md \
        src/asya-runtime/README.md \
        src/asya-sidecar/README.md \
        src/asya-sidecar/pkg/messages/message.go
git commit -m "docs: update fan-out documentation for yield-only model

Fan-out is now exclusively via generator/yield handlers.
List returns are treated as single payload values.
Fanout ID semantics unchanged (index-based suffixing)."
```

---

### Task 10: Full test suite validation

**Step 1: Run all unit tests**

```bash
make test-unit
```

**Step 2: Run linter**

```bash
make lint
```

**Step 3: Run integration tests**

```bash
make test-integration
```

**Step 4: Fix any remaining failures**

**Step 5: Final commit if needed**

```bash
git add -A
git commit -m "fix: resolve remaining test failures from yield-only fan-out migration"
```

---

### Task 11: Close bead and push

**Step 1: Update bead status**

```bash
bd update asya-51j1 --status=in_progress
```

**Step 2: Push branch**

```bash
bd sync
git push -u origin feature/asya-51j1-yield-fanout
```

**Step 3: Close bead**

```bash
bd close asya-51j1 --reason="Implemented yield-only fan-out. List-return removed."
bd sync
```

---

## Out of Scope (tracked separately)

- **Async handler support** (`async def` + `return`/`yield`): Covered by agentic compiler RFC Phase 3
- **Multi-frame streaming wire protocol**: Future optimization for yield handlers (currently all yields collected in memory before sending). Tracked in agentic compiler RFC.
- **AGENTS.md / CLAUDE.md updates**: Update handler documentation after merge to main
