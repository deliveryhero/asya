# Mock Runtime for Testing

This directory contains a shared mock runtime used by all integration and E2E tests.

## Purpose

Provides test handlers covering various scenarios:
- **Happy path**: Normal successful processing
- **Error handling**: ValueError, MemoryError, CUDA OOM
- **Timeouts**: Configurable sleep durations
- **Fan-out**: Returning multiple results
- **Empty responses**: Returning None to abort pipeline
- **Large payloads**: Testing size limits
- **Unicode**: Testing UTF-8 encoding
- **Pipeline**: Multi-step processing (doubler, incrementer)
- **Progress**: SSE streaming tests

## Structure

```
tests/mock_runtime/
├── handlers.py          # All test handlers (merged from both integration tests)
├── Dockerfile           # Shared Docker image for mock runtime
├── requirements.txt     # Dependencies (currently none)
└── README.md           # This file
```

## Available Handlers

See `handlers.py` for the complete list. Key handlers:

- `handlers.happy_path` - Simple successful processing
- `handlers.echo_handler` - Echo payload or message
- `handlers.error_handler` - Raises ValueError
- `handlers.oom_handler` - Raises MemoryError
- `handlers.cuda_oom_handler` - Raises CUDA OOM error
- `handlers.timeout_handler` - Sleeps for specified duration
- `handlers.fanout_handler` - Returns list of results
- `handlers.empty_response_handler` - Returns None
- `handlers.pipeline_doubler` - Doubles input value
- `handlers.pipeline_incrementer` - Adds 5 to input value
- `handlers.progress_handler` - Multi-step processing
- `handlers.large_payload_handler` - Large data responses
- `handlers.unicode_handler` - International characters
- `handlers.nested_data_handler` - Deeply nested structures
- `handlers.null_values_handler` - None/null values
- `handlers.conditional_handler` - Action-based behavior
- `handlers.metadata_handler` - Route metadata testing

## Usage in Integration Tests

### Docker Compose

```yaml
services:
  my-test-actor:
    build:
      context: ../../../  # Root of repo
      dockerfile: tests/mock_runtime/Dockerfile
    environment:
      - ASYA_HANDLER=handlers.echo_handler  # Choose handler
      - ASYA_SOCKET_PATH=/tmp/sockets/app.sock
    volumes:
      - socket:/tmp/sockets
```

### Standalone Docker

```bash
# Build image
docker build -t asya-mock-runtime -f tests/mock_runtime/Dockerfile .

# Run with specific handler
docker run \
  -e ASYA_HANDLER=handlers.progress_handler \
  -e ASYA_SOCKET_PATH=/tmp/sockets/app.sock \
  asya-mock-runtime
```

## Migration from Old Structure

Previously, each integration test had its own `runtime/handlers.py`:
- `tests/integration/sidecar-vs-runtime/runtime/handlers.py` (13 handlers)
- `tests/integration/gateway-vs-actors/runtime/handlers.py` (6 handlers)

Now all handlers are merged into `tests/mock_runtime/handlers.py` (19 total handlers).

### Benefits

1. **Single source of truth**: All test handlers in one place
2. **Reusability**: Share handlers across integration and E2E tests
3. **Consistency**: Same handlers behave identically everywhere
4. **Maintainability**: Update once, benefit everywhere
5. **Documentation**: All handlers documented in one file

## Adding New Handlers

To add a new test handler:

1. Add function to `handlers.py`:
   ```python
   def my_new_handler(msg: Dict[str, Any]) -> Dict[str, Any]:
       """
       My new handler: Does something interesting.

       Tests: What scenario this handler tests.
       """
       payload = msg.get("payload", {})
       # ... your logic ...
       return {"status": "processed"}
   ```

2. Use in tests via `ASYA_HANDLER=handlers.my_new_handler`

3. No need to rebuild - handlers are copied at build time

## Notes

- **No dependencies**: All handlers use stdlib only (for simplicity)
- **Progress reporting**: Handled automatically by Go sidecar
- **Type hints**: All handlers use type annotations for clarity
- **Documentation**: Each handler has detailed docstring
