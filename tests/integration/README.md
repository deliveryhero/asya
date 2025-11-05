# Integration Tests

This directory contains end-to-end integration tests for the Asya framework.

## Directory Structure

```
tests/integration/
├── sidecar-vs-runtime/      # Tests sidecar ↔ runtime communication protocol
│   ├── docker-compose.yml   # Multi-runtime setup for 13 test scenarios
│   ├── Makefile             # Test runner with docker-compose
│   ├── rabbitmq-definitions.json  # RabbitMQ queue configuration
│   ├── rabbitmq.conf        # RabbitMQ settings
│   ├── runtime/
│   │   ├── Dockerfile       # Runtime container with test handlers
│   │   ├── handlers.py      # Test handler functions
│   │   └── requirements.txt # Runtime dependencies (none currently)
│   └── tests/
│       ├── Dockerfile       # Test runner container
│       ├── requirements.txt # pytest, pika, requests
│       └── test_sidecar_with_runtime.py  # Comprehensive sidecar tests
│
├── gateway-vs-actors/       # Tests gateway ↔ actors ↔ terminal actors flow
│   ├── docker-compose.yml   # Full gateway + actors + terminal actors
│   ├── Makefile             # Test runner with docker-compose
│   ├── rabbitmq-definitions.json  # RabbitMQ queue configuration
│   ├── rabbitmq.conf        # RabbitMQ settings
│   ├── gateway-routes.yaml  # Gateway MCP tool definitions
│   ├── runtime/
│   │   ├── Dockerfile       # Runtime container with gateway test handlers
│   │   ├── handlers.py      # Gateway test handlers with heartbeat support
│   │   └── requirements.txt # requests for heartbeat API calls
│   └── tests/
│       ├── Dockerfile       # Test runner container
│       ├── requirements.txt # pytest, requests, sseclient-py
│       ├── test_messaging.py  # Basic gateway messaging and SSE
│       ├── test_progress_tracking.py  # Comprehensive progress tests
│       └── test_progress_standalone.py  # Simple progress smoke tests
│
└── README.md                # This file
```

## Running Tests

### Quick Start

Run all integration tests from the root directory:
```bash
make test-integration
```

Run specific test suites:
```bash
make test-integration-sidecar   # Sidecar ↔ Runtime tests
make test-integration-gateway   # Gateway ↔ Actors tests
```

### Configurable Logging

Control Python test logging verbosity with the `ASYA_LOG_LEVEL` environment variable:

**Available levels:**
- `DEBUG` - Most verbose (shows all `logging.debug()` statements)
- `INFO` - Standard output (default)
- `WARNING` - Warnings and errors only
- `ERROR` - Errors only
- `CRITICAL` - Critical errors only

**Usage examples:**
```bash
# Run with DEBUG logging to see all logging.debug() output
make test-integration ASYA_LOG_LEVEL=DEBUG

# Run with WARNING level to reduce noise
make test-integration ASYA_LOG_LEVEL=WARNING

# Run specific suite with DEBUG logging
make test-integration-gateway ASYA_LOG_LEVEL=DEBUG

# Default behavior (INFO level)
make test-integration
```

**Direct docker-compose usage:**
```bash
# With DEBUG logging
cd tests/integration/gateway-vs-actors
ASYA_LOG_LEVEL=DEBUG docker compose -p gw up --build --abort-on-container-exit

# With WARNING logging
cd tests/integration/sidecar-vs-runtime
ASYA_LOG_LEVEL=WARNING docker compose -p sc up --build --abort-on-container-exit
```

**Note:** The `-p gw` and `-p sc` project names prevent resource conflicts when running both test suites.

## Test Suites

### 1. Sidecar ↔ Runtime Tests (`sidecar-vs-runtime/`)

**Purpose:** Tests the complete actor runtime and sidecar message flow in isolation, without the gateway.

**Architecture:**
- 13 runtime+sidecar pairs, each testing a specific scenario
- RabbitMQ for message queuing (port 5673 to avoid conflicts)
- Single test file with comprehensive scenario coverage
- Each scenario uses a dedicated queue and handler

**Test Scenarios:**
- `happy_path` - Simple successful processing
- `error_handler` - ValueError to test fatal error handling
- `oom_handler` - MemoryError to test RAM OOM detection
- `cuda_oom_handler` - CUDA OOM simulation with cache clearing
- `timeout_handler` - Long sleep to trigger sidecar timeout
- `fanout_handler` - Multiple results for fan-out routing
- `empty_response_handler` - None return to test happy-end routing
- `large_payload_handler` - Large data to test protocol size limits
- `unicode_handler` - International characters for UTF-8 testing
- `null_values_handler` - None/null values in JSON
- `conditional_handler` - Dynamic behavior based on payload
- `nested_data_handler` - Deeply nested JSON structures
- `echo_handler` - Simple pass-through for multi-step routing

**Key Features:**
- Shared socket volume for runtime-sidecar communication
- Independent runtime containers with different handlers
- Tests protocol edge cases without gateway complexity

**Docker Compose Services:**
- 1 RabbitMQ instance (with management UI)
- 13 runtime containers (one per handler)
- 13 sidecar containers (one per runtime)
- 1 test runner container (pytest)
- Total: ~28 containers

### 2. Gateway ↔ Actors Tests (`gateway-vs-actors/`)

**Purpose:** Tests the complete end-to-end flow from MCP gateway through actor pipelines to terminal actors.

**Architecture:**
- PostgreSQL for gateway job storage
- RabbitMQ for message queuing (port 5672)
- Gateway with configurable MCP tools (gateway-routes.yaml)
- 6 actor runtimes (echo, progress, doubler, incrementer, error, timeout)
- 2 terminal actors (happy-end, error-end) from asya-actors
- Full sidecar setup for all actors

**Test Files:**
- `test_messaging.py` - Basic gateway API, SSE streaming, echo tool
- `test_progress_tracking.py` - Comprehensive progress tracking with heartbeats
- `test_progress_standalone.py` - Simple smoke tests for progress features

**Test Scenarios:**
- MCP tool invocation via JSON-RPC 2.0
- Job status tracking (Pending → Running → Succeeded/Failed)
- SSE progress streaming with real-time heartbeat updates
- Multi-step pipelines (doubler → incrementer)
- Progress calculation accuracy (single-step and multi-step routes)
- Concurrent job progress tracking
- Error handling with terminal actor retry logic
- Timeout handling
- Terminal actor final status reporting to gateway

**Key Features:**
- Full database migration with sqitch
- Gateway heartbeat API (`POST /jobs/{id}/heartbeat`)
- Terminal actors report final status to gateway
- Tests complete lifecycle: gateway → actors → terminal → gateway

**Docker Compose Services:**
- 1 PostgreSQL instance (gateway job storage)
- 1 RabbitMQ instance (with management UI)
- 1 database migration container (sqitch, runs once)
- 1 gateway instance (MCP server)
- 8 runtime containers (6 test actors + 2 terminal actors)
- 8 sidecar containers (one per runtime)
- 1 test runner container (pytest)
- Total: ~21 containers

## RabbitMQ Configuration

Both test suites use **RabbitMQ definition files** for queue setup instead of init scripts. This provides:
- Clean, declarative configuration
- No separate setup containers needed
- Faster startup times
- Version-controlled queue definitions

### Definition Files
- `sidecar-vs-runtime/rabbitmq-definitions.json` - Queues for sidecar ↔ runtime tests
- `gateway-vs-actors/rabbitmq-definitions.json` - Queues for gateway ↔ actors tests

### Port Separation
- `sidecar-vs-runtime/` uses ports 5673 (AMQP) and 15673 (Management)
- `gateway-vs-actors/` uses ports 5672 (AMQP) and 15672 (Management)

This separation prevents port conflicts when running both test suites simultaneously.

### How It Works
RabbitMQ automatically loads definitions on startup via:
```yaml
volumes:
  - ./rabbitmq-definitions.json:/etc/rabbitmq/definitions.json:ro
  - ./rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf:ro
```

The `rabbitmq.conf` contains:
```
management.load_definitions = /etc/rabbitmq/definitions.json
```

### Adding New Queues
To add a new queue, edit the appropriate definition file:

1. Add queue to `queues` array:
```json
{
  "name": "new-queue",
  "vhost": "/",
  "durable": true,
  "auto_delete": false,
  "arguments": {}
}
```

2. Add binding to `bindings` array:
```json
{
  "source": "asya",
  "vhost": "/",
  "destination": "new-queue",
  "destination_type": "queue",
  "routing_key": "new-queue",
  "arguments": {}
}
```

### Exporting Current Configuration
To export the current RabbitMQ configuration (useful for updating definitions):
```bash
# From running RabbitMQ container (adjust container name)
docker exec -it <container> rabbitmqadmin export /tmp/definitions.json
docker cp <container>:/tmp/definitions.json ./rabbitmq-definitions.json
```

Or via Management UI:
1. Open http://localhost:15672 (gateway tests) or http://localhost:15673 (sidecar tests)
2. Login with guest/guest
3. Navigate to Overview → Export definitions
4. Save to the appropriate test directory (`sidecar-vs-runtime/` or `gateway-vs-actors/`)

## Adding New Tests

All test files are organized in `tests/` subdirectories within each integration test suite. The entire `tests/` directory is mounted in Docker, making it easy to add new tests without modifying `docker-compose.yml`.

### Adding a New Test Case (to existing handlers)

1. Create a new `test_*.py` file in the appropriate `tests/` directory:
   - `sidecar-vs-runtime/tests/` - For sidecar ↔ runtime protocol tests
   - `gateway-vs-actors/tests/` - For gateway ↔ actors E2E tests

2. Write your pytest tests following the existing patterns

3. Run the tests - no docker-compose.yml changes needed!

**Example:**
```bash
# Add a new test file
echo 'def test_my_feature(): ...' > gateway-vs-actors/tests/test_my_feature.py

# Run tests - automatically picks up the new file
make test-integration-gateway
```

### Adding a New Test Scenario (new handler + runtime + sidecar)

For `sidecar-vs-runtime/` tests, if you need a new handler function:

1. **Add handler to `runtime/handlers.py`:**
   ```python
   def my_new_handler(msg: dict) -> dict:
       """Description of what this handler tests."""
       payload = msg.get("payload", {})
       # Your test logic here
       return {"result": "processed"}
   ```

2. **Add runtime service to `docker-compose.yml`:**
   ```yaml
   asya-mytest-runtime:
     build:
       context: ./runtime
       dockerfile: Dockerfile
     command: ["python", "/opt/asya/asya_runtime.py"]
     environment:
       - ASYA_HANDLER=handlers.my_new_handler
       - ASYA_SOCKET_PATH=/tmp/sockets/mytest.sock
       - ASYA_SOCKET_CHMOD=666
       - ASYA_LOG_LEVEL=${ASYA_LOG_LEVEL:-INFO}
     volumes:
       - sockets:/tmp/sockets
       - ../../../src/asya-runtime/asya_runtime.py:/opt/asya/asya_runtime.py:ro
     healthcheck:
       test: ["CMD", "test", "-S", "/tmp/sockets/mytest.sock"]
       interval: 2s
       timeout: 1s
       retries: 15
   ```

3. **Add sidecar service to `docker-compose.yml`:**
   ```yaml
   asya-mytest-sidecar:
     build:
       context: ../../../src/asya-sidecar
       dockerfile: Dockerfile
     depends_on:
       rabbitmq:
         condition: service_healthy
       asya-mytest-runtime:
         condition: service_healthy
     environment:
       - ASYA_RABBITMQ_URL=amqp://guest:guest@rabbitmq:5673/
       - ASYA_RABBITMQ_EXCHANGE=asya
       - ASYA_QUEUE_NAME=test-mytest-queue
       - ASYA_SOCKET_PATH=/tmp/sockets/mytest.sock
       - ASYA_RUNTIME_TIMEOUT=30s
       - ASYA_STEP_HAPPY_END=happy-end
       - ASYA_STEP_ERROR_END=error-end
       - ASYA_LOG_LEVEL=${ASYA_LOG_LEVEL:-INFO}
     volumes:
       - sockets:/tmp/sockets
   ```

4. **Add queue to `rabbitmq-definitions.json`** (see RabbitMQ Configuration section below)

5. **Add test dependency** in `tester` service `depends_on` section

6. **Write pytest test** in `tests/test_sidecar_with_runtime.py`

For `gateway-vs-actors/` tests, follow similar steps but also update `gateway-routes.yaml` if adding a new MCP tool.

This structure ensures you never forget to mount new test files in docker-compose.yml.

## Test Dependencies

Each test suite has separate `requirements.txt` files for test runners and runtime handlers:

### Test Runner Dependencies (`tests/requirements.txt`)
- `sidecar-vs-runtime/tests/requirements.txt`:
  - `pytest` - Test framework
  - `requests` - HTTP client for RabbitMQ Management API
  - `pika` - RabbitMQ/AMQP client library

- `gateway-vs-actors/tests/requirements.txt`:
  - `pytest` - Test framework
  - `requests` - HTTP client for gateway API calls
  - `sseclient-py` - Server-Sent Events (SSE) client

### Runtime Handler Dependencies (`runtime/requirements.txt`)
- `sidecar-vs-runtime/runtime/requirements.txt` - Empty (no dependencies)
- `gateway-vs-actors/runtime/requirements.txt`:
  - `requests` - For sending heartbeats to gateway API

### Adding Dependencies

1. **For test files:** Edit `<suite>/tests/requirements.txt`
   ```bash
   # Example: add pytest plugin for gateway tests
   echo "pytest-asyncio>=0.21.0" >> gateway-vs-actors/tests/requirements.txt
   ```

2. **For runtime handlers:** Edit `<suite>/runtime/requirements.txt`
   ```bash
   # Example: add library for sidecar test handlers
   echo "numpy>=1.24.0" >> sidecar-vs-runtime/runtime/requirements.txt
   ```

3. Run tests - dependencies are automatically installed in Docker containers
