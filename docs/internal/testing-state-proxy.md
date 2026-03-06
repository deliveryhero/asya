# Testing: State Proxy / Storage Backends

How storage backends (S3/GCS/Redis) are exercised across all test levels.
The state proxy appears in unit tests, component tests, integration tests,
and E2E tests — each with different infrastructure and scope.

## Storage Support Matrix

| Backend | Unit | Component | Integration | E2E |
|---------|------|-----------|-------------|-----|
| S3 LWW | ✅ (moto) | ✅ | ✅ (sqs-s3, rabbitmq-minio) | ✅ CI |
| S3 CAS | ✅ (moto) | ✅ | — | — |
| S3 passthrough | ✅ (moto) | ✅ | — | — |
| GCS LWW | ✅ (mock) | ✅ | ✅ (pubsub-gcs) | ✅ CI |
| GCS CAS | ✅ (mock) | ✅ | — | — |
| Redis CAS | ✅ (mock) | ✅ | — | — |

## Unit Tests

**Location**: `src/asya-state-proxy/tests/`

Each connector has its own unit test file. The mock strategy differs by SDK:

**S3 connectors** — use `moto` (`@mock_aws` decorator):
```python
from moto import mock_aws

@pytest.fixture
@mock_aws
def s3_bucket():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=TEST_BUCKET)
    yield TEST_BUCKET
```

`moto` intercepts all `boto3` HTTP calls in-process. No Docker, no LocalStack.
Required env vars are set via `monkeypatch.setenv` in an `autouse` fixture.

**GCS connectors** — use `unittest.mock` patching the `google.cloud.storage` SDK:
```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_storage_client():
    with patch("asya_state_proxy.connectors.gcs_buffered_lww.connector.storage.Client") as mock:
        yield mock
```

GCS has no equivalent of `moto`. The SDK is patched at import time. Generation
numbers (used for CAS) are simulated with `MagicMock` return values.

**Redis connector** — patches `redis.Redis` similarly to the GCS approach.

Run:
```bash
make -C src/asya-state-proxy test-unit
# or directly:
uv run pytest src/asya-state-proxy/tests/
```

## Component Tests: State Proxy

**Location**: `testing/component/state-proxy/`

Tests a single connector in a Docker Compose environment with a real storage
emulator. The connector process runs alongside a minimal runtime stub that
exercises the connector's `read`/`write`/`cas` operations via Unix socket.

```
testing/component/state-proxy/
├── profiles/
│   ├── s3-lww.yml          # LocalStack S3 + s3-buffered-lww connector
│   ├── s3-cas.yml          # LocalStack S3 + s3-buffered-cas connector
│   ├── s3-passthrough.yml  # LocalStack S3 + s3-passthrough connector
│   ├── gcs-lww.yml         # fake-gcs-server + gcs-buffered-lww connector
│   ├── gcs-cas.yml         # fake-gcs-server + gcs-buffered-cas connector
│   └── redis-cas.yml       # Redis + redis-buffered-cas connector
└── compose/
    ├── state-actors.yml    # state-proxy-connector + asya-state-ops-runtime services
    └── tester.yml          # pytest runner
```

Run:
```bash
make -C testing/component/state-proxy test-one CONNECTOR_PROFILE=gcs-lww
make -C testing/component/state-proxy test      # all six profiles
```

### Profile assembly

Each profile `include`s the relevant shared emulator from `testing/shared/compose/`:

```yaml
# profiles/gcs-lww.yml
include:
  - path: ../../../shared/compose/fake-gcs.yml
```

The shared emulator files are:
- `testing/shared/compose/fake-gcs.yml` — fake-gcs-server + `storage-setup` bucket init
- `testing/shared/compose/s3.yml` — LocalStack for S3
- `testing/shared/compose/redis.yml` — Redis

### Bucket pre-creation

The `storage-setup` service in `fake-gcs.yml` reads
`testing/shared/compose/configs/gcs-buckets.txt` and creates each bucket via the
fake-gcs REST API before tests run:

```
POST http://fake-gcs:4443/storage/v1/b?project=test
body: {"name": "<bucket>"}
```

S3 equivalent: `storage-setup` calls `aws s3 mb s3://<bucket>` against LocalStack.

### fake-gcs-server quirks

- `-scheme http`: No TLS. Required because the GCS Python SDK must be pointed at
  `STORAGE_EMULATOR_HOST=http://...` to skip certificate validation.
- `-public-host fake-gcs:4443`: Must match the in-container hostname. The SDK
  uses this to construct object self-links. Mismatch causes test failures where
  the SDK rejects responses as coming from the wrong host.
- At the E2E level, `-public-host` is set to the full cluster DNS name:
  `fake-gcs.asya-system.svc.cluster.local:4443`

## Integration Tests: Gateway + Actors (x-sink / x-sump)

**Location**: `testing/integration/gateway-actors/`

Tests the full pipeline including x-sink persistence. The profile name encodes
both transport and storage: `<transport>-<storage>`.

```
testing/integration/gateway-actors/
└── profiles/
    ├── sqs-s3.yml          # S3 LWW connector via LocalStack S3
    ├── rabbitmq-minio.yml  # S3 LWW connector via MinIO (S3-compatible)
    └── pubsub-gcs.yml      # GCS LWW connector via fake-gcs-server
```

For `ASYA_STORAGE=gcs`, the Makefile automatically appends a GCS overlay:
```makefile
ifeq ($(ASYA_STORAGE),gcs)
COMPOSE_FILES += -f compose/crew-gcs-overlay.yml
endif
```

This overlay replaces the default S3 connector image and injects
`STORAGE_EMULATOR_HOST` into the x-sink container.

Run:
```bash
make -C testing/integration/gateway-actors test-one ASYA_TRANSPORT=pubsub ASYA_STORAGE=gcs
make -C testing/integration/gateway-actors test      # all profiles
```

### What gets tested here that unit/component tests don't

- The `x-sink` crew actor correctly persists the processed envelope to storage
  after routing through sidecar → runtime → x-sink sidecar → x-sink runtime
- The connector image (built from `Dockerfile.gcs-buffered-lww`) loads and
  connects successfully inside a real container
- Bucket existence is verified: tests assert the object appeared in the bucket
  using the emulator API

### S3 list_objects pagination

LocalStack `list_objects` returns at most 1000 objects. Cleanup between tests
uses `list_objects_v2` with `ContinuationToken` to handle full buckets. The
utility is in `src/asya-testing/asya_testing/utils/s3.py:delete_all_objects_in_bucket`.
This was a real bug in early test runs (#256).

## E2E Tests: Kind Cluster

**Location**: `testing/e2e/`

Full Kubernetes deployment with Crossplane-managed AsyncActors, KEDA autoscaling,
and the crew actors using a real connector image running as a sidecar container.

```
testing/e2e/
├── profiles/
│   ├── sqs-s3.yaml         # crew.persistence.backend: s3
│   └── pubsub-gcs.yaml     # crew.persistence.backend: gcs
├── charts/
│   ├── s3/                 # LocalStack chart (shared SQS + S3)
│   ├── gcs/                # fake-gcs-server chart
│   └── minio/              # MinIO chart
└── tests/
    └── test_state_persistence_e2e.py
```

### Crew chart persistence values

The crew chart (`deploy/helm-charts/asya-crew/`) reads `persistence.*` and
injects the right connector image and env vars:

```yaml
# profiles/pubsub-gcs.yaml (GCS example)
crew:
  persistence:
    enabled: true
    backend: gcs
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:latest
    config:
      bucket: asya-results
      project: test-project
      emulatorHost: "http://fake-gcs.asya-system.svc.cluster.local:4443"
```

The chart translates `backend + config` into env vars on the state proxy container:
`STORAGE_BACKEND`, `STORAGE_BUCKET`, `STORAGE_EMULATOR_HOST`, and
backend-specific credential vars.

### NodePort mapping

The storage emulator must be reachable from pytest (running on the host).
`kind-config.yaml` binds Kind NodePorts to localhost for all profiles:

| Storage | NodePort | Host port | In-cluster service |
|---------|----------|-----------|-------------------|
| LocalStack S3 | 30567 | 4567 | `localstack-s3.asya-system` |
| LocalStack SQS | 30566 | 4566 | `localstack-sqs.asya-system` |
| fake-gcs | 30443 | 4443 | `fake-gcs.asya-system` |
| MinIO | 30900 | 9000 | `minio.<namespace>` |

`.env.<profile>` exposes these as `STORAGE_EMULATOR_HOST=http://127.0.0.1:<port>`.

### Connector image build and loading

For E2E tests, connector images are built locally and loaded into Kind:

```bash
# scripts/deploy.sh (pubsub-gcs profile)
docker build -t asya-state-proxy-gcs-buffered-lww:dev \
  -f src/asya-state-proxy/Dockerfile.gcs-buffered-lww \
  src/asya-state-proxy/
kind load docker-image asya-state-proxy-gcs-buffered-lww:dev \
  --name asya-e2e-pubsub-gcs
```

For component and integration tests, Docker Compose builds the image from the
same Dockerfile using a `build:` context — no pre-loading needed.

### fake-gcs-server in E2E vs Docker Compose

The `-public-host` flag must match the hostname the GCS SDK will use to reach the
server. This differs between test levels:

- **Docker Compose** (component/integration): `-public-host fake-gcs:4443`
  (Docker network name)
- **E2E / Kind**: `-public-host fake-gcs.asya-system.svc.cluster.local:4443`
  (full cluster DNS)

Both run in HTTP mode (`-scheme http`) to avoid TLS.

### Test-side assertions

Tests verify that `x-sink` persisted the envelope by reading from the emulator.
Utilities live in `src/asya-testing/asya_testing/utils/`:

- `s3.py`: `wait_for_envelope_in_s3(bucket, task_id, timeout)` — polls via `boto3`
- GCS equivalents use `google-cloud-storage` SDK with `STORAGE_EMULATOR_HOST`

## Adding a New Storage Backend

### 1. Unit tests

- Create `src/asya-state-proxy/tests/test_<backend>_<mode>.py`
- AWS-compatible: use `moto` (`@mock_aws`)
- GCP/other: patch the SDK client class via `unittest.mock.patch`
- Implement `StateProxyConnector` ABC in
  `src/asya-state-proxy/asya_state_proxy/connectors/<backend>_<mode>/connector.py`

### 2. Shared emulator definition (component + integration)

- Add `testing/shared/compose/<backend>.yml` with:
  - The emulator service (official image, not Bitnami)
  - A `storage-setup` service that pre-creates buckets/tables, with a healthcheck
  - A `configs/<backend>-buckets.txt` listing resources to create

### 3. Component tests

- Add `testing/component/state-proxy/profiles/<backend>-<mode>.yml` including
  the shared emulator and extending `compose/state-actors.yml`
- Add `CONNECTOR_PROFILE=<backend>-<mode>` to `make test` in the Makefile

### 4. Integration tests (gateway-actors)

- Add `testing/integration/gateway-actors/profiles/<transport>-<backend>.yml`
- If the crew chart needs an overlay to select the new connector, add
  `compose/crew-<backend>-overlay.yml` and wire it into the Makefile condition

### 5. E2E tests

- Add `testing/e2e/charts/<backend>/` Helm chart (`Deployment` + `NodePort Service`)
- Add `extraPortMappings` entry to `kind-config.yaml` (unused ports are harmless)
- Add `condition: storage.<backend>.enabled` release to `helmfile.yaml.gotmpl`
- Update profile YAML with `crew.persistence.backend`, connector image, and config
- Update `scripts/deploy.sh` to build and `kind load` the connector image
- Update the crew chart to inject the new backend's env vars

## Relationship Between Transport and Storage

Transport and storage are independent dimensions in the test matrix. The
`sqs-s3` profile uses SQS for message passing and S3 for result persistence.
The `pubsub-gcs` profile uses Pub/Sub and GCS. There is no technical coupling —
any transport can be paired with any storage backend. The current profiles
reflect the cloud provider pairing (AWS: SQS+S3, GCP: Pub/Sub+GCS) for
credential simplicity, not technical necessity.
