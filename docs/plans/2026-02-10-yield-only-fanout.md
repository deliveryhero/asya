# Yield-Only Fan-Out Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove list-return fan-out from the runtime, replace with yield/generator-based fan-out with a streaming wire protocol — each yield sends a frame immediately to the sidecar, which forwards it to the next queue immediately.

**Architecture:** The current protocol is batch: runtime collects all responses into a JSON array, sends it in one shot, sidecar parses the array and loops. The new protocol is streaming: the Unix socket connection stays open for the handler's lifetime, the runtime sends one length-prefixed frame per yield (or one frame for return), terminated by an `{"type": "end"}` sentinel. The sidecar reads frames in a loop, forwarding each to the next queue immediately. This enables true streaming fan-out where each yielded result flows through the system as soon as it's produced.

**Tech Stack:** Python (asya-runtime), Go (asya-sidecar), Python (asya-testing handlers), pytest, go test

**Bead:** asya-51j1

---

## New Handler Model

```
+------------------+----------------------------+-------------------------------+
| Handler Type     | Signature                  | Behavior                      |
+------------------+----------------------------+-------------------------------+
| sync return      | def h(p) -> dict           | ONE output frame + end frame  |
| async return     | async def h(p) -> dict     | ONE output frame + end frame  |
| sync yield       | def h(p) -> Generator      | N output frames + end frame   |
| async yield      | async def h(p) -> AsyncGen | N output frames + end frame   |
+------------------+----------------------------+-------------------------------+
```

- `return None` = end frame only (no output, sidecar routes to happy-end)
- `return <value>` = one output frame + end frame (even if value is a list)
- `yield <value>` = one output frame per yield, then end frame after generator exhausts
- async variants are out of scope for this bead (agentic compiler RFC Phase 3)

## Wire Protocol Change

### Current Protocol (Batch)

```
Sidecar → Runtime:  [4-byte length][request JSON]
Runtime → Sidecar:  [4-byte length][JSON array of all responses]
                    Connection closes.
```

### New Protocol (Streaming)

```
Sidecar → Runtime:  [4-byte length][request JSON]
Runtime → Sidecar:  [4-byte length][response frame 1 JSON]
Runtime → Sidecar:  [4-byte length][response frame 2 JSON]  (only for generators)
...
Runtime → Sidecar:  [4-byte length][{"type": "end"} JSON]
                    Connection closes.
```

**Frame types:**

| Frame | JSON Shape | Meaning |
|-------|-----------|---------|
| Response | `{"payload": ..., "route": ...}` | One output message (may include `headers`) |
| Error | `{"error": "code", "details": {...}}` | Handler error, abort |
| End | `{"type": "end"}` | No more frames, handler done |

**Examples:**

Return handler (`return {"result": 42}`):
```
Frame 1: {"payload": {"result": 42}, "route": {"actors": [...], "current": 1}}
Frame 2: {"type": "end"}
```

Return None (abort):
```
Frame 1: {"type": "end"}
```

Generator handler (yields 3 items):
```
Frame 1: {"payload": {"index": 0}, "route": {"actors": [...], "current": 1}}
Frame 2: {"payload": {"index": 1}, "route": {"actors": [...], "current": 1}}
Frame 3: {"payload": {"index": 2}, "route": {"actors": [...], "current": 1}}
Frame 4: {"type": "end"}
```

Error:
```
Frame 1: {"error": "processing_error", "details": {"message": "...", ...}}
Frame 2: {"type": "end"}
```

---

### Task 1: Runtime — Streaming wire protocol for return handlers

Change `_handle_request` and `handle_requests` to send frames instead of a JSON array.
Start with return handlers only (no generator support yet).

**Files:**
- Modify: `src/asya-runtime/asya_runtime.py:367-468,515-535`
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write failing test — runtime sends frames instead of JSON array**

The existing test helper `handle_and_receive` reads one length-prefixed message and parses it as a JSON array. We need a new helper `handle_and_receive_frames` that reads multiple length-prefixed frames until it sees `{"type": "end"}`:

```python
def receive_frames(client_sock) -> list[dict]:
    """Read streaming frames from runtime until end sentinel."""
    frames = []
    while True:
        length_bytes = recv_exact(client_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        data = recv_exact(client_sock, length)
        frame = json.loads(data.decode("utf-8"))
        if frame.get("type") == "end":
            break
        frames.append(frame)
    return frames


def handle_and_receive_frames(server_sock, client_sock, user_func) -> list[dict]:
    """Handle request and receive streaming frames."""
    _handle_request_streaming(server_sock, user_func)
    return receive_frames(client_sock)
```

Then write the actual test:

```python
def test_return_handler_sends_frames(self, socket_pair, mock_env):
    """Return handler sends one response frame + end frame."""
    server_sock, client_sock = socket_pair

    def simple_handler(payload):
        return {"result": payload["value"] * 2}

    request = {
        "payload": {"value": 5},
        "route": {"actors": ["me"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    frames = handle_and_receive_frames(server_sock, client_sock, simple_handler)

    assert len(frames) == 1
    assert frames[0]["payload"] == {"result": 10}
    assert frames[0]["route"]["current"] == 1
```

**Step 2: Run test to verify it fails**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_return_handler_sends_frames"
```
Expected: FAIL (runtime still sends JSON array, not streaming frames).

**Step 3: Refactor runtime to send streaming frames**

Change `_handle_request` to no longer return `list[dict]`. Instead, create a new function `_handle_request_streaming` that sends frames directly on the connection:

```python
def _send_frame(conn: socket.socket, frame: dict[str, Any]):
    """Send a single frame with length-prefix."""
    data = json.dumps(frame).encode("utf-8")
    _send_message(conn, data)


def _send_end_frame(conn: socket.socket):
    """Send the end sentinel frame."""
    _send_frame(conn, {"type": "end"})


def _handle_request_streaming(conn: socket.socket, user_func: Any):
    """Handle a single request, sending response frames as they're produced."""
    # Read and parse message (same as before)
    try:
        length_bytes = _recv_exact(conn, 4)
        length = struct.unpack(">I", length_bytes)[0]
        data = _recv_exact(conn, length)
    except ConnectionError as exc:
        _send_frame(conn, _error_response("connection_error", exc))
        _send_end_frame(conn)
        return
    except Exception as exc:
        logger.error(f"ERROR: Connection handling failed:\n{traceback.format_exc()}")
        _send_frame(conn, _error_response("connection_error", exc))
        _send_end_frame(conn)
        return

    try:
        message: dict[str, Any] = _parse_message_json(data)
        if ASYA_ENABLE_VALIDATION:
            message = _validate_message(message)
        logger.debug(f"Received message: {len(data)} bytes")
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError) as exc:
        _send_frame(conn, _error_response("msg_parsing_error", exc))
        _send_end_frame(conn)
        return

    # Call handler and stream frames
    try:
        if ASYA_HANDLER_MODE == "payload":
            _handle_payload_mode_streaming(conn, message, user_func)
        elif ASYA_HANDLER_MODE == "envelope":
            _handle_envelope_mode_streaming(conn, message, user_func)
        else:
            raise ValueError(f"Invalid ASYA_HANDLER_MODE={ASYA_HANDLER_MODE}")
    except Exception as exc:
        logger.error(f"[DIAG] Exception caught in handler: type={type(exc).__name__}, msg={exc}")
        logger.exception("Fatal error on processing input message")
        _send_frame(conn, _error_response("processing_error", exc))

    _send_end_frame(conn)


def _handle_payload_mode_streaming(conn: socket.socket, message: dict, user_func: Any):
    """Handle payload mode: send one frame per result."""
    output_route = message["route"].copy()
    output_route["current"] = message["route"]["current"] + 1
    headers = message.get("headers")

    def _build_payload_frame(payload_value: Any) -> dict[str, Any]:
        frame: dict[str, Any] = {"payload": payload_value, "route": output_route}
        if headers is not None:
            frame["headers"] = headers
        return frame

    if inspect.isgeneratorfunction(user_func):
        for p in user_func(message["payload"]):
            _send_frame(conn, _build_payload_frame(p))
    else:
        result = user_func(message["payload"])
        if result is not None:
            _send_frame(conn, _build_payload_frame(result))


def _handle_envelope_mode_streaming(conn: socket.socket, message: dict, user_func: Any):
    """Handle envelope mode: send one frame per result."""
    if inspect.isgeneratorfunction(user_func):
        for out in user_func(message):
            if ASYA_ENABLE_VALIDATION:
                out = _validate_message(
                    out,
                    expected_current_actor=_get_current_actor(message),
                    input_route=message["route"],
                )
            _send_frame(conn, out)
    else:
        result = user_func(message)
        if result is not None:
            if ASYA_ENABLE_VALIDATION:
                result = _validate_message(
                    result,
                    expected_current_actor=_get_current_actor(message),
                    input_route=message["route"],
                )
            _send_frame(conn, result)
```

Update `_error_response` to return a single dict (not a list):

```python
def _error_response(code: str, exc: Exception | None = None) -> dict[str, Any]:
    """Returns standardized error response dict."""
    error: dict[str, Any] = {"error": code}
    if exc is not None:
        error["details"] = {
            "message": str(exc),
            "type": type(exc).__name__,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
    return error
```

Update `handle_requests` main loop to use the new streaming function:

```python
            try:
                _handle_request_streaming(conn, func)

            except BrokenPipeError:
                logger.warning("Client disconnected")

            except Exception as e:
                logger.critical(f"Failed to send response: {type(e)}: {e}")

            finally:
                conn.close()
```

**Step 4: Run test to verify it passes**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_return_handler_sends_frames"
```

**Step 5: Update ALL existing test helpers to use frame-based protocol**

The existing `handle_and_receive` helper must be updated to read frames instead of a JSON array. This will cause many existing tests to start passing again with the new protocol.

**Step 6: Run full runtime test suite**

```bash
make -C src/asya-runtime test-unit
```
Expected: Many tests will fail because they use the old `handle_and_receive` — update them.

**Step 7: Commit**

```bash
git add src/asya-runtime/asya_runtime.py src/asya-runtime/tests/test_asya_runtime.py
git commit -m "feat(runtime): streaming wire protocol for return handlers

Each return sends one response frame + end sentinel frame.
return None sends only end frame (abort/happy-end).
Replaces batch JSON array protocol."
```

---

### Task 2: Runtime — Add list-return-is-single-payload test

**Files:**
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

**Step 1: Write test — list return is single payload, not fan-out**

```python
def test_list_return_is_single_payload(self, socket_pair, mock_env):
    """Returning a list produces ONE frame with the list AS the payload."""
    server_sock, client_sock = socket_pair

    def list_handler(payload):
        return [{"a": 1}, {"b": 2}, {"c": 3}]

    request = {
        "payload": {"test": "list"},
        "route": {"actors": ["me"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    frames = handle_and_receive_frames(server_sock, client_sock, list_handler)

    assert len(frames) == 1
    assert frames[0]["payload"] == [{"a": 1}, {"b": 2}, {"c": 3}]
```

**Step 2: Run — should pass from Task 1 changes**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k test_list_return_is_single_payload"
```

**Step 3: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): verify list return is single payload, not fan-out"
```

---

### Task 3: Runtime — Generator fan-out (streaming)

**Files:**
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

Generator support was added in Task 1's implementation. This task adds comprehensive tests.

**Step 1: Write test — generator yields 3 items, produces 3 frames**

```python
def test_generator_fanout_payload_mode(self, socket_pair, mock_env):
    """Generator handler: each yield produces one frame immediately."""
    server_sock, client_sock = socket_pair

    def gen_handler(payload):
        for i in range(payload["count"]):
            yield {"index": i}

    request = {
        "payload": {"count": 3},
        "route": {"actors": ["gen"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    frames = handle_and_receive_frames(server_sock, client_sock, gen_handler)

    assert len(frames) == 3
    for i, frame in enumerate(frames):
        assert frame["payload"]["index"] == i
        assert frame["route"]["current"] == 1
```

**Step 2: Write test — generator in envelope mode**

```python
def test_generator_fanout_envelope_mode(self, socket_pair, mock_env_envelope):
    """Generator in envelope mode yields multiple envelopes."""
    server_sock, client_sock = socket_pair

    def gen_envelope_handler(envelope):
        route = envelope["route"].copy()
        route["current"] += 1
        for i in range(3):
            yield {"payload": {"index": i}, "route": route}

    request = {
        "payload": {},
        "route": {"actors": ["me", "next"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    frames = handle_and_receive_frames(server_sock, client_sock, gen_envelope_handler)

    assert len(frames) == 3
    for i, frame in enumerate(frames):
        assert frame["payload"]["index"] == i
        assert frame["route"]["current"] == 1
```

**Step 3: Write test — headers preserved across yields**

```python
def test_generator_preserves_headers(self, socket_pair, mock_env):
    """Headers preserved in every yielded frame."""
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

    frames = handle_and_receive_frames(server_sock, client_sock, gen_handler)

    assert len(frames) == 2
    for frame in frames:
        assert frame["headers"]["trace_id"] == "abc-123"
```

**Step 4: Write test — generator error mid-stream**

```python
def test_generator_error_mid_stream(self, socket_pair, mock_env):
    """Generator that raises after yielding produces error frame."""
    server_sock, client_sock = socket_pair

    def failing_gen(payload):
        yield {"index": 0}
        raise ValueError("mid-stream failure")

    request = {
        "payload": {},
        "route": {"actors": ["gen"], "current": 0},
    }
    send_message(client_sock, json.dumps(request).encode())

    frames = handle_and_receive_frames(server_sock, client_sock, failing_gen)

    # First yield succeeded, then error frame
    assert len(frames) == 2
    assert frames[0]["payload"]["index"] == 0
    assert frames[1]["error"] == "processing_error"
```

**Step 5: Run all generator tests**

```bash
make -C src/asya-runtime test-unit PYTEST_OPTS="-v -k generator"
```

**Step 6: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): comprehensive generator fan-out streaming tests"
```

---

### Task 4: Fix broken existing runtime tests

The following existing tests relied on the old batch JSON array protocol and/or list-return fan-out. Each must be updated to use `handle_and_receive_frames` and generator handlers.

**Files:**
- Modify: `src/asya-runtime/tests/test_asya_runtime.py`

**Tests to update:**

| Test | Line | Fix |
|------|------|-----|
| `test_handle_request_fanout_list_output` (payload) | ~1057 | Rewrite: use generator handler |
| `test_handle_request_fanout_list_output` (envelope) | ~1135 | Rewrite: use generator handler |
| `test_handler_returns_empty_list` | ~147 | `return []` is now single payload `[]` |
| `test_handler_fanout_with_actor_validation` | ~465 | Rewrite: use generator |
| `test_handler_fanout_with_invalid_actor_name` | ~502 | Rewrite: use generator |
| `test_class_handler_fanout_payload_mode` | ~1545 | Rewrite: class with generator method |
| `test_headers_preserved_in_fanout_payload_mode` | ~2022 | Rewrite: use generator |
| `test_envelope_mode_fanout` | ~2165 | Rewrite: use generator |
| ALL other tests | various | Update `handle_and_receive` → `handle_and_receive_frames` |

**Step 1: Update test helper**

Replace `handle_and_receive` with `handle_and_receive_frames` throughout the test file. The old helper parsed JSON array; the new one reads streaming frames.

**Step 2: Convert each fan-out test to use generator handlers**

Pattern: Replace `return [item1, item2, ...]` with `yield item1; yield item2; ...`

**Step 3: Update `test_handler_returns_empty_list`**

```python
def test_handler_returns_empty_list(self, ...):
    """return [] now produces one frame with [] as payload (not abort)."""
    def handler(payload):
        return []

    frames = handle_and_receive_frames(...)
    assert len(frames) == 1
    assert frames[0]["payload"] == []
```

**Step 4: Run full runtime test suite**

```bash
make -C src/asya-runtime test-unit
```
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/asya-runtime/tests/test_asya_runtime.py
git commit -m "test(runtime): migrate all tests to streaming frame protocol

Fan-out tests use generator handlers.
List return tests verify single-payload behavior.
All tests use handle_and_receive_frames helper."
```

---

### Task 5: Sidecar — Streaming frame reader

Change `CallRuntime` in the sidecar to read multiple length-prefixed frames until end sentinel, processing each response as it arrives.

**Files:**
- Modify: `src/asya-sidecar/internal/runtime/client.go:85-122`
- Test: `src/asya-sidecar/internal/runtime/client_test.go`

**Step 1: Write failing test — sidecar reads streaming frames**

```go
func TestClient_CallRuntime_StreamingFrames(t *testing.T) {
    // Create mock runtime that sends:
    //   Frame 1: {"payload": {"index": 0}, "route": {"actors": ["a"], "current": 1}}
    //   Frame 2: {"payload": {"index": 1}, "route": {"actors": ["a"], "current": 1}}
    //   Frame 3: {"type": "end"}
    socketPath := setupMockStreamingRuntime(t, []map[string]any{
        {"payload": map[string]any{"index": 0}, "route": map[string]any{"actors": []string{"a"}, "current": 1}},
        {"payload": map[string]any{"index": 1}, "route": map[string]any{"actors": []string{"a"}, "current": 1}},
    })

    client := NewClient(socketPath, 5*time.Second)
    responses, err := client.CallRuntime(context.Background(), []byte(`{"payload":{},"route":{"actors":["a"],"current":0}}`))

    require.NoError(t, err)
    assert.Len(t, responses, 2)
    // Verify each response
}

func setupMockStreamingRuntime(t *testing.T, frames []map[string]any) string {
    t.Helper()
    socketPath := filepath.Join(t.TempDir(), "test.sock")

    listener, err := net.Listen("unix", socketPath)
    require.NoError(t, err)
    t.Cleanup(func() { listener.Close() })

    go func() {
        conn, err := listener.Accept()
        if err != nil { return }
        defer conn.Close()

        // Read request (ignore)
        RecvSocketData(conn)

        // Send response frames
        for _, frame := range frames {
            data, _ := json.Marshal(frame)
            SendSocketData(conn, data)
        }
        // Send end frame
        endFrame, _ := json.Marshal(map[string]string{"type": "end"})
        SendSocketData(conn, endFrame)
    }()

    return socketPath
}
```

**Step 2: Run test to verify it fails**

```bash
make -C src/asya-sidecar test-unit TEST_OPTS="-run TestClient_CallRuntime_StreamingFrames -v"
```

**Step 3: Implement streaming frame reader in CallRuntime**

```go
// CallRuntime sends a message to the runtime and reads streaming response frames.
// Returns responses collected from all frames, empty slice for abort, or error.
func (c *Client) CallRuntime(ctx context.Context, data []byte) ([]RuntimeResponse, error) {
    ctx, cancel := context.WithTimeout(ctx, c.timeout)
    defer cancel()

    var dialer net.Dialer
    conn, err := dialer.DialContext(ctx, "unix", c.socketPath)
    if err != nil {
        return nil, fmt.Errorf("failed to connect to runtime socket: %w", err)
    }
    defer func() { _ = conn.Close() }()

    deadline, _ := ctx.Deadline()
    _ = conn.SetDeadline(deadline)

    if err := SendSocketData(conn, data); err != nil {
        return nil, fmt.Errorf("failed to send message to runtime: %w", err)
    }

    // Read streaming frames until end sentinel
    var responses []RuntimeResponse
    for {
        frameData, err := RecvSocketData(conn)
        if err != nil {
            return nil, fmt.Errorf("failed to read frame from runtime: %w", err)
        }

        // Check for end sentinel
        var raw map[string]json.RawMessage
        if err := json.Unmarshal(frameData, &raw); err != nil {
            return nil, fmt.Errorf("failed to parse frame: %w", err)
        }

        if typeField, ok := raw["type"]; ok {
            var frameType string
            if err := json.Unmarshal(typeField, &frameType); err == nil && frameType == "end" {
                break
            }
        }

        // Parse as RuntimeResponse
        var response RuntimeResponse
        if err := json.Unmarshal(frameData, &response); err != nil {
            return nil, fmt.Errorf("failed to parse runtime response frame: %w", err)
        }
        responses = append(responses, response)
    }

    return responses, nil
}
```

**Step 4: Run test to verify it passes**

```bash
make -C src/asya-sidecar test-unit TEST_OPTS="-run TestClient_CallRuntime_StreamingFrames -v"
```

**Step 5: Write test for single-frame return handler**

```go
func TestClient_CallRuntime_SingleFrame(t *testing.T) {
    socketPath := setupMockStreamingRuntime(t, []map[string]any{
        {"payload": map[string]any{"result": 42}, "route": map[string]any{"actors": []string{"a"}, "current": 1}},
    })

    client := NewClient(socketPath, 5*time.Second)
    responses, err := client.CallRuntime(context.Background(), []byte(`{"payload":{},"route":{"actors":["a"],"current":0}}`))

    require.NoError(t, err)
    assert.Len(t, responses, 1)
}
```

**Step 6: Write test for empty response (abort)**

```go
func TestClient_CallRuntime_EmptyAbort(t *testing.T) {
    // Only end frame, no response frames
    socketPath := setupMockStreamingRuntime(t, []map[string]any{})

    client := NewClient(socketPath, 5*time.Second)
    responses, err := client.CallRuntime(context.Background(), []byte(`{"payload":{},"route":{"actors":["a"],"current":0}}`))

    require.NoError(t, err)
    assert.Len(t, responses, 0)
}
```

**Step 7: Write test for error frame**

```go
func TestClient_CallRuntime_ErrorFrame(t *testing.T) {
    socketPath := setupMockStreamingRuntime(t, []map[string]any{
        {"error": "processing_error", "details": map[string]any{"message": "test error"}},
    })

    client := NewClient(socketPath, 5*time.Second)
    responses, err := client.CallRuntime(context.Background(), []byte(`{"payload":{},"route":{"actors":["a"],"current":0}}`))

    require.NoError(t, err)
    assert.Len(t, responses, 1)
    assert.True(t, responses[0].IsError())
}
```

**Step 8: Run all client tests**

```bash
make -C src/asya-sidecar test-unit TEST_OPTS="-run TestClient -v"
```

**Step 9: Commit**

```bash
git add src/asya-sidecar/internal/runtime/client.go src/asya-sidecar/internal/runtime/client_test.go
git commit -m "feat(sidecar): streaming frame reader for runtime protocol

CallRuntime now reads length-prefixed frames in a loop until
end sentinel {type: end}. Supports single-frame (return),
multi-frame (generator), and error frames."
```

---

### Task 6: Sidecar — Router handles streaming responses

The router's `handleRuntimeResponses` and `handleSuccessResponse` continue to work as-is since `CallRuntime` still returns `[]RuntimeResponse`. The only change: `totalResponses` is now determined after reading all frames (which still happens before routing starts).

**Note:** True per-frame forwarding (sidecar forwards each frame as it reads it, before the generator finishes) is a future optimization. For now, `CallRuntime` collects all frames into `[]RuntimeResponse` and the router processes them as before. This keeps the sidecar change minimal while establishing the new wire protocol.

**Files:**
- Read-only verification: `src/asya-sidecar/internal/router/router.go`
- Test: `src/asya-sidecar/internal/router/router_test.go`

**Step 1: Run existing router tests**

```bash
make -C src/asya-sidecar test-unit TEST_OPTS="-run TestRouter -v"
```
Expected: ALL PASS (router code unchanged, mock runtime still works).

**Step 2: Update existing fan-out router tests if needed**

The existing `TestRouter_ProcessMessage_FanOut` test mocks `CallRuntime` to return `[]RuntimeResponse` directly — it doesn't go through the wire protocol. These tests should still pass unchanged.

**Step 3: Commit (only if changes needed)**

---

### Task 7: Update test handlers in asya-testing

**Files:**
- Modify: `src/asya-testing/asya_testing/handlers/payload.py:117-145,278-300`

**Step 1: Convert fanout_handler to generator**

```python
from collections.abc import Generator

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

**Step 2: Update empty_response_handler and none_response_handler**

```python
def empty_response_handler(payload: dict[str, Any]) -> None:
    """Returns None to abort pipeline. Routes to happy-end."""
    return None

def none_response_handler(payload: dict[str, Any]) -> None:
    """Returns None to abort pipeline. Routes to happy-end."""
    return None
```

**Step 3: Split conditional_handler — remove "fanout" action**

```python
def conditional_handler(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Conditional handler. Supports: success, error, oom, slow, empty."""
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
    """Fan-out variant of conditional_handler. Yields multiple results."""
    count = payload.get("count", 2)
    for i in range(count):
        yield {"index": i, "action": "fanout"}
```

**Step 4: Commit**

```bash
git add src/asya-testing/asya_testing/handlers/payload.py
git commit -m "feat(testing): convert fan-out handlers to generators

fanout_handler uses yield. conditional_handler split into
separate non-generator and generator variants.
empty/none handlers return None."
```

---

### Task 8: Integration tests

**Files:**
- Verify: `testing/integration/sidecar-runtime/tests/test_sidecar_with_runtime.py`

**Step 1: Run integration tests**

```bash
make -C testing/integration/sidecar-runtime test
```

The integration test `test_fanout` uses `fanout_handler` which is now a generator. The runtime detects this via `inspect.isgeneratorfunction()` and streams frames. The sidecar reads frames until end sentinel. Everything should work end-to-end.

**Step 2: If test_fanout fails, debug**

- Check that `inspect.isgeneratorfunction()` works for the handler loaded via `importlib`
- Check Docker Compose logs for frame protocol errors
- Verify sidecar correctly reads end sentinel

**Step 3: Commit (if changes needed)**

```bash
git add testing/integration/
git commit -m "fix(integration): update fan-out tests for streaming protocol"
```

---

### Task 9: Update documentation

**Files:**
- Modify: `docs/architecture/protocols/actor-actor.md:86-114`
- Modify: `src/asya-runtime/README.md:195-202`
- Modify: `src/asya-sidecar/README.md:43-48`
- Modify: `src/asya-sidecar/pkg/messages/message.go:12-24`

**Step 1: Update actor-actor.md — Fan-Out section**

Replace "Fan-Out (Array)" with:

```markdown
### Fan-Out (Generator/Yield)

Runtime handler uses `yield` to produce multiple outputs:
```python
def process(payload):
    for item in payload["items"]:
        yield {"processed": item}
```

**Action**: Each yield sends a frame immediately to sidecar, which routes it to next actor

**Fanout ID semantics**:

- First message retains original ID (for SSE streaming compatibility)
- Subsequent messages receive suffixed IDs: `{original_id}-{index}`
- All fanout children have `parent_id` set to original message ID

**Note**: Returning a list from a handler does NOT trigger fan-out.
A returned list is treated as a single payload value.
```

**Step 2: Update Empty Response**

```markdown
### Empty Response

Runtime returns `None`:

**Action**: Sidecar routes message to `happy-end` (no increment)
```

**Step 3: Update runtime README**

Replace list-return fan-out example with yield example.

**Step 4: Update sidecar README**

Replace "Array (fan-out)" with "Generator (fan-out): multiple response frames via yield".

**Step 5: Update message.go doc comment**

```go
// Fanout ID Semantics:
// When an actor handler uses yield (generator), the runtime sends multiple response
// frames over the Unix socket. The sidecar reads each frame and creates a separate
// message for routing. The first message retains the original ID; subsequent messages
// receive suffixed IDs following the pattern: {original_id}-{index}.
```

**Step 6: Commit**

```bash
git add docs/ src/asya-runtime/README.md src/asya-sidecar/README.md src/asya-sidecar/pkg/messages/message.go
git commit -m "docs: update protocol docs for streaming yield fan-out"
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

---

### Task 11: Close bead and push

```bash
bd update asya-51j1 --status=in_progress
bd sync
git push -u origin feature/asya-51j1-yield-fanout
bd close asya-51j1 --reason="Streaming yield-only fan-out implemented. List-return removed."
bd sync
git push
```

---

## Out of Scope (tracked separately)

| Item | Tracked By |
|------|-----------|
| Async handler support (`async def` + `return`/`yield`) | Agentic compiler RFC Phase 3 |
| Per-frame forwarding in sidecar (forward each frame to queue as it's read, before generator finishes) | Future optimization — currently CallRuntime collects all frames then router processes |
| `partial: true` event classification (stream to gateway vs route to queue) | Agentic compiler RFC streaming support |
| AGENTS.md / CLAUDE.md handler docs | Update after merge to main |
