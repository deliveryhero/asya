# E2E Testing: State Proxy / Storage Backends

How storage backends (S3/GCS) are wired into E2E tests, specifically for the
`x-sink` and `x-sump` crew actors and the state proxy sidecar.
Captured during PRs #250, #256, #258.

## Overview

The state proxy is a sidecar container that the `x-sink` and `x-sump` crew actors
use to persist processed envelopes. In E2E tests, a storage emulator replaces the
real cloud service. The emulator must be reachable from both:

- **Inside the cluster** (state proxy sidecar, connector container)
- **Outside the cluster** (pytest, for asserting bucket contents)

## Storage Backends

| Backend | Emulator | Profile |
|---------|----------|---------|
| S3 | LocalStack (`localstack/localstack`) | `sqs-s3` |
| GCS | fake-gcs-server (`fsouza/fake-gcs-server`) | `pubsub-gcs` |
| MinIO | MinIO (`minio/minio`) | `rabbitmq-minio` (disabled in CI) |

## File Locations

```
testing/e2e/
├── profiles/
│   ├── sqs-s3.yaml              # crew.persistence.backend: s3
│   └── pubsub-gcs.yaml          # crew.persistence.backend: gcs
├── charts/
│   ├── s3/                      # LocalStack chart (shared SQS + S3)
│   ├── gcs/                     # fake-gcs-server chart
│   └── minio/                   # MinIO chart
└── tests/
    └── test_state_persistence_e2e.py   # State proxy E2E tests
```

The crew chart (`deploy/helm-charts/asya-crew/`) reads:
- `crew.persistence.backend` — selects connector image and config schema
- `crew.persistence.connector.image` — connector container image
- `crew.persistence.config` — backend-specific config (bucket, endpoint, credentials)

## How Storage is Configured in a Profile

### S3 (sqs-s3 profile)

```yaml
# profiles/sqs-s3.yaml
storage:
  s3:
    enabled: true

crew:
  persistence:
    enabled: true
    backend: s3
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:dev
    config:
      bucket: asya-results
      endpoint: http://localstack-s3.asya-system.svc.cluster.local:4566
      region: us-east-1
      accessKey: test
      secretKey: test
  x-sink:
    env:
      AWS_ACCESS_KEY_ID: "test"
      AWS_SECRET_ACCESS_KEY: "test"
```

The LocalStack chart deploys a single pod serving both SQS (port 4566) and S3
(also port 4566 but differentiated by service name: `localstack-sqs` vs
`localstack-s3`).

### GCS (pubsub-gcs profile)

```yaml
# profiles/pubsub-gcs.yaml
storage:
  gcs:
    enabled: true

crew:
  persistence:
    enabled: true
    backend: gcs
    config:
      bucket: asya-results
      project: test-project
      emulatorHost: "http://fake-gcs.asya-system.svc.cluster.local:4443"
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:latest
  x-sink:
    env:
      PUBSUB_EMULATOR_HOST: "pubsub-emulator.asya-system.svc.cluster.local:8085"
```

The crew chart translates `backend: gcs` + `config.emulatorHost` into
`STORAGE_EMULATOR_HOST` env var on the state proxy container.

## fake-gcs-server Details

`fsouza/fake-gcs-server` is a Go reimplementation of the GCS JSON API. Key
characteristics:

- **In-memory + filesystem backends**: E2E tests use `filesystem` backend with
  an `emptyDir` volume (data is lost on pod restart, which is fine for testing)
- **Pre-created buckets**: The GCS chart uses an init container to `mkdir /data/<bucket>`
  before the server starts. Buckets listed in `charts/gcs/values.yaml` (`asya-results`,
  `asya-errors`) are created at startup.
- **HTTP mode**: The server runs with `-scheme http` (not HTTPS) to avoid TLS
  complexity in tests. The GCS Python SDK is configured with
  `STORAGE_EMULATOR_HOST=http://...` to use HTTP.
- **`-public-host` flag**: Must match the in-cluster service hostname
  (`fake-gcs.<namespace>.svc.cluster.local:4443`). The SDK uses this to construct
  signed URLs and object self-links. If this doesn't match, the SDK may reject
  responses or generate incorrect URLs.

**Why not MinIO for GCS?** MinIO implements the S3 API, not the GCS JSON API.
The GCS SDK (`google-cloud-storage`) is not S3-compatible. `fake-gcs-server` is
the only production-ready GCS emulator.

## NodePort Mapping

The storage emulator must be reachable from the pytest process running on the host.
This requires a `NodePort` service + `extraPortMappings` in `kind-config.yaml`:

| Storage | NodePort | Host port | Service name |
|---------|----------|-----------|--------------|
| LocalStack S3 | 30567 | 4567 | `localstack-s3.asya-system` |
| LocalStack SQS | 30566 | 4566 | `localstack-sqs.asya-system` |
| fake-gcs | 30443 | 4443 | `fake-gcs.asya-system` |
| MinIO | 30900 | 9000 | `minio.<namespace>` |

The `.env.<profile>` file uses these host ports:

```bash
# .env.pubsub-gcs
STORAGE_EMULATOR_HOST=http://127.0.0.1:30443
GCS_BUCKET=asya-results
```

## State Proxy Connector Images

Each storage backend has dedicated connector images built from `src/asya-state-proxy/`:

| Backend | Image | Dockerfile |
|---------|-------|------------|
| S3 LWW | `asya-state-proxy-s3-buffered-lww` | `Dockerfile.s3-buffered-lww` |
| S3 CAS | `asya-state-proxy-s3-buffered-cas` | `Dockerfile.s3-buffered-cas` |
| GCS LWW | `asya-state-proxy-gcs-buffered-lww` | `Dockerfile.gcs-buffered-lww` |
| GCS CAS | `asya-state-proxy-gcs-buffered-cas` | `Dockerfile.gcs-buffered-cas` |
| Redis CAS | `asya-state-proxy-redis-cas` | `Dockerfile.redis-cas` |

For E2E tests, only the LWW variant is used (simpler, no CAS conflict resolution
needed). The image is built locally and loaded into Kind:

```bash
# scripts/deploy.sh (pubsub-gcs profile)
docker build -t asya-state-proxy-gcs-buffered-lww:dev \
  -f src/asya-state-proxy/Dockerfile.gcs-buffered-lww \
  src/asya-state-proxy/
kind load docker-image asya-state-proxy-gcs-buffered-lww:dev --name asya-e2e-pubsub-gcs
```

## Crew Helm Chart: Persistence Overlay

The crew chart (`deploy/helm-charts/asya-crew/`) selects the connector image and
injects backend-specific env vars based on `persistence.backend`:

```yaml
# crew chart values (simplified)
persistence:
  enabled: true
  backend: gcs       # "s3" | "gcs" | "redis"
  connector:
    image: ...       # connector image (backend-specific)
  config:
    bucket: asya-results
    # S3 fields: endpoint, region, accessKey, secretKey
    # GCS fields: project, emulatorHost
    # Redis fields: addr
```

The chart translates these into env vars on the state proxy container:
- `STORAGE_BACKEND` — connector type selection
- `STORAGE_BUCKET` — bucket/prefix
- `STORAGE_EMULATOR_HOST` — emulator endpoint (dev/test only)
- Backend-specific vars (credentials, region, etc.)

## Test-Side Assertions

Tests read from the storage emulator to verify that `x-sink` persisted the
processed envelope. The utilities are in `src/asya-testing/asya_testing/utils/`:

- `s3.py`: `wait_for_envelope_in_s3(bucket, task_id, timeout)` — polls via `boto3`
- GCS equivalents use `google-cloud-storage` SDK with `STORAGE_EMULATOR_HOST`

**S3 pagination note**: LocalStack `list_objects` returns max 1000 objects. For
buckets with many results, tests must use `list_objects_v2` with `ContinuationToken`
pagination. This was fixed in PR #256 (`delete_all_objects_in_bucket` in `s3.py`).

## Adding a New Storage Backend

1. **Add emulator chart** in `testing/e2e/charts/<backend>/` with:
   - `Deployment`: use official image, pre-create buckets/tables in init container
   - `Service`: `NodePort` type with a fixed `nodePort`
   - `values.yaml`: list of buckets to pre-create

2. **Add NodePort to `kind-config.yaml`** (shared config, unused ports are fine).

3. **Update `.env.<profile>`** with `STORAGE_EMULATOR_HOST` and credentials.

4. **Implement connector** in `src/asya-state-proxy/`:
   - New subdirectory + `Dockerfile.<backend>-<mode>`
   - Implement `StateProxyConnector` ABC
   - Add connector to `src/asya-state-proxy/pyproject.toml` extras

5. **Update crew chart** to handle the new `persistence.backend` value in
   the connector image selection and env var injection logic.

6. **Update profile YAML** with:
   - `storage.<backend>.enabled: true`
   - `crew.persistence.backend: <backend>`
   - `crew.persistence.connector.image: ...`
   - `crew.persistence.config: ...` (backend-specific fields)

7. **Add test utilities** in `src/asya-testing/asya_testing/utils/<backend>.py`
   for asserting bucket contents from the test side.

## Relationship Between Transport and Storage

Transport and storage are independent dimensions in the profile matrix. The
`sqs-s3` profile uses SQS for message passing and S3 for result persistence.
The `pubsub-gcs` profile uses Pub/Sub and GCS. There is no technical coupling —
any transport can be paired with any storage backend. The current profiles
reflect the cloud provider pairing (AWS: SQS+S3, GCP: Pub/Sub+GCS) for
credential simplicity, not technical necessity.
