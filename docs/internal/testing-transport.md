# Testing: Transport Backends

How message transport (SQS, Pub/Sub, RabbitMQ) is exercised across all test levels.
The same transport appears at four different abstraction layers, each with different
infrastructure and scope.

## Transport Support Matrix

| Transport | Unit | Component | Integration | E2E |
|-----------|------|-----------|-------------|-----|
| RabbitMQ | — | ✅ | ✅ | ❌ disabled in CI |
| SQS | ✅ (moto) | ✅ | ✅ | ✅ CI |
| Pub/Sub | ✅ (mock) | — | ✅ | ✅ CI |

Unit tests for the transport layer live in `src/asya-sidecar/` (Go) and
`src/asya-testing/asya_testing/clients/` (Python). Component tests for the
sidecar are in `testing/component/sidecar/`.

## Unit Tests

**Location**: `src/asya-sidecar/transport/`

The sidecar transport implementations (`sqs.go`, `pubsub.go`, `rabbitmq.go`) are
unit-tested with interface mocks — no real queues involved.

For the **Python test client** (`src/asya-testing/`):
- `SQSClient` — tested via `moto` (`@mock_aws` decorator), which intercepts all
  `boto3` calls in-process
- `PubSubClient` — tested via `unittest.mock` patching `google.cloud.pubsub_v1`
- `RabbitMQClient` — tested via `unittest.mock` patching `pika`

Key mock entry points:
```python
# SQS: moto intercepts boto3 at the HTTP layer
from moto import mock_aws

@mock_aws
def test_send_receive():
    client = SQSClient(endpoint_url="http://localhost:4566", ...)
    ...

# GCS/PubSub: patch the SDK client class itself
with patch("google.cloud.pubsub_v1.PublisherClient") as mock_pub:
    ...
```

`TransportTimeouts` (`src/asya-testing/asya_testing/fixtures/transport.py`) groups
SQS and Pub/Sub together with longer timeouts (30/60/120s) vs RabbitMQ (20/30/120s)
because both use polling or emulator gRPC, not immediate push delivery.

## Component Tests: Sidecar

**Location**: `testing/component/sidecar/`

Tests the sidecar binary in isolation against a real transport emulator. No
runtime or actor code runs — only the sidecar's message receive/send loop.

```
testing/component/sidecar/
├── profiles/
│   ├── rabbitmq.yml     # docker-compose: sidecar + RabbitMQ
│   └── sqs.yml          # docker-compose: sidecar + LocalStack SQS
└── tests/
    └── test_sidecar.py
```

Run:
```bash
make -C testing/component/sidecar test-one ASYA_TRANSPORT=sqs
make -C testing/component/sidecar test-one ASYA_TRANSPORT=rabbitmq
```

There is no Pub/Sub component profile for the sidecar yet. Pub/Sub is first
exercised at the integration level.

## Integration Tests: Sidecar + Runtime

**Location**: `testing/integration/sidecar-runtime/`

Tests the sidecar ↔ runtime pair end-to-end within Docker Compose. Messages
flow: test client → transport emulator → sidecar → Unix socket → runtime → response.

```
testing/integration/sidecar-runtime/
├── profiles/
│   ├── rabbitmq.yml    # RabbitMQ transport
│   ├── sqs.yml         # LocalStack SQS
│   └── pubsub.yml      # GCP Pub/Sub emulator (gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators)
├── configs/
│   └── pubsub-topics.txt   # List of topics/subscriptions to pre-create
└── compose/
    └── tester.yml
```

Run:
```bash
make -C testing/integration/sidecar-runtime test-one ASYA_TRANSPORT=pubsub
make -C testing/integration/sidecar-runtime test              # all three transports
```

### Pub/Sub emulator topic pre-creation

Pub/Sub requires topics and subscriptions to exist before the sidecar starts.
The `queue-setup` service (in `profiles/pubsub.yml`) reads
`configs/pubsub-topics.txt` and creates each topic+subscription via the emulator
REST API:

```
PUT http://pubsub:8085/v1/projects/test-project/topics/{topic}
PUT http://pubsub:8085/v1/projects/test-project/subscriptions/{topic}
    body: {"topic": "projects/test-project/topics/{topic}", "ackDeadlineSeconds": 60}
```

The `tester` container starts only after `queue-setup` completes successfully
(`condition: service_completed_successfully`). If a test creates new actors, it
must also create their topics via the emulator REST API.

### Shared emulator definitions

The shared `testing/shared/compose/pubsub.yml` defines the Pub/Sub emulator
service. Profiles include it with:

```yaml
include:
  - path: ../../../shared/compose/pubsub.yml
```

## Integration Tests: Gateway + Actors

**Location**: `testing/integration/gateway-actors/`

Tests the gateway ↔ sidecar ↔ runtime ↔ x-sink pipeline. The profile name
combines transport and storage: `ASYA_TRANSPORT-ASYA_STORAGE`.

```
testing/integration/gateway-actors/
└── profiles/
    ├── sqs-s3.yml          # LocalStack SQS + LocalStack S3
    ├── rabbitmq-minio.yml  # RabbitMQ + MinIO
    └── pubsub-gcs.yml      # Pub/Sub emulator + fake-gcs-server
```

Run:
```bash
make -C testing/integration/gateway-actors test-one ASYA_TRANSPORT=pubsub ASYA_STORAGE=gcs
```

The GCS profile requires an overlay (`compose/crew-gcs-overlay.yml`) that
configures the x-sink crew actor to use the GCS connector instead of the default
S3 connector. This overlay is added automatically when `ASYA_STORAGE=gcs`.

## E2E Tests: Kind Cluster

**Location**: `testing/e2e/`

Full Kubernetes deployment with Crossplane, the injector, gateway, KEDA, and crew
actors. Transport is selected at the profile level. See
[testing-e2e-transport.md](testing-e2e-transport.md) for the full E2E-specific
documentation including the Crossplane composition pipeline, the Pub/Sub emulator
OAuth workaround, and the `gcpProject` / `_transport_suffix` pattern.

## Adding a New Transport

Transport support must be added at each level independently.

### 1. Unit tests

- Add a mock client in `src/asya-testing/asya_testing/clients/<transport>.py`
  implementing `TransportClient` ABC
- Add a branch in `transport_client` fixture in
  `src/asya-testing/asya_testing/fixtures/transport.py`
- Update `TransportTimeouts` if the new transport has different polling latency

### 2. Component tests

- Add `testing/component/sidecar/profiles/<transport>.yml` using the shared
  emulator definition from `testing/shared/compose/<transport>.yml` (create the
  shared file if it doesn't exist)
- Add `make test-<transport>` target in `testing/component/sidecar/Makefile`

### 3. Integration tests (sidecar-runtime)

- Add `testing/integration/sidecar-runtime/profiles/<transport>.yml`
- If the transport requires topic/subscription pre-creation (like Pub/Sub),
  add a `queue-setup` service that runs before the `tester`
- Add `make test-<transport>` target in the sidecar-runtime Makefile

### 4. Integration tests (gateway-actors)

- Add `testing/integration/gateway-actors/profiles/<transport>-<storage>.yml`
- If the new transport uses a different storage backend, also add the storage
  configuration (see [testing-state-proxy.md](testing-state-proxy.md))

### 5. E2E tests

See [testing-e2e-transport.md](testing-e2e-transport.md) for the full checklist
(Crossplane composition, Kind NodePort, profile YAML, skip logic, CI matrix).
