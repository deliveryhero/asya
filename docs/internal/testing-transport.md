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

# Pub/Sub: patch the SDK client class itself
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
actors. Transport is selected at the profile level.

Active profiles in CI:

| Profile | Transport | Storage | Status |
|---------|-----------|---------|--------|
| `sqs-s3` | LocalStack SQS | LocalStack S3 | ✅ CI |
| `pubsub-gcs` | GCP Pub/Sub emulator | fake-gcs-server | ✅ CI |
| `rabbitmq-minio` | RabbitMQ | MinIO | ❌ disabled in CI |

```
testing/e2e/
├── kind-config.yaml              # Kind cluster config (port mappings for all profiles)
├── Makefile                      # make up / make trigger-tests PROFILE=sqs-s3
├── profiles/
│   ├── sqs-s3.yaml              # Helm values for sqs-s3 profile
│   ├── pubsub-gcs.yaml          # Helm values for pubsub-gcs profile
│   ├── .env.sqs-s3              # Env vars exported to pytest (host-side)
│   └── .env.pubsub-gcs
├── charts/
│   ├── helmfile.yaml.gotmpl     # Assembles infra from profiles + charts
│   ├── sqs/                     # LocalStack SQS Helm chart
│   └── pubsub/                  # GCP Pub/Sub emulator chart
└── tests/
    ├── conftest.py              # Transport client fixture selection
    └── test_crossplane_e2e.py   # Crossplane XRD/composition tests (transport-aware)
```

### How a profile works

The profile YAML (`profiles/<profile>.yaml`) is the single source of truth for
the entire cluster. It controls which Helm releases are deployed:

```yaml
# profiles/pubsub-gcs.yaml
transport:
  pubsub:
    enabled: true   # deploys pubsub emulator chart
crossplane:
  providers:
    gcp:
      enabled: true  # deploys provider-gcp-pubsub + GCP ProviderConfig
```

After `make up`, `make trigger-tests` sources `.env.<profile>` which maps
emulator NodePorts to localhost for pytest:

```bash
# .env.pubsub-gcs
ASYA_TRANSPORT=pubsub
PUBSUB_EMULATOR_HOST=127.0.0.1:30085   # NodePort → Kind → emulator pod
```

The `127.0.0.1` addresses work because `kind-config.yaml` binds Kind node
NodePorts to localhost via `extraPortMappings`. All profiles share one Kind
config — unused ports are harmless:

```yaml
# kind-config.yaml
extraPortMappings:
  - containerPort: 30566   # LocalStack SQS → localhost:4566
    hostPort: 4566
  - containerPort: 30085   # Pub/Sub emulator → localhost:8085
    hostPort: 8085
```

### Crossplane composition

Each transport has its own composition:
- `composition-sqs.yaml` — creates SQS queue via `provider-aws-sqs`
- `composition-pubsub.yaml` — creates Topic + Subscription via `provider-gcp-pubsub`
- `composition-rabbitmq.yaml` — creates RabbitMQ queue via `provider-kubernetes`

Pipeline steps (same structure across compositions):

```
input (XAsyncActor)
  → render-queue                 # creates the queue/topic managed resource
  → render-sa                    # creates ServiceAccount (IRSA/workload identity)
  → fetch-environment-configs    # reads EnvironmentConfigs by label selector
  → function-asya-overlays       # merges overlays → context["asya/resolved-spec"]
  → render-scaledobject          # reads context["asya/resolved-spec"] for KEDA
  → render-deployment            # reads context["asya/resolved-spec"] for containers
  → function-auto-ready          # sets READY condition
```

**Bug pattern to avoid**: All three steps that touch overlay data must agree on
the context key. `function-asya-overlays` writes `"asya/resolved-spec"`.
Using `"asya.sh/resolved-spec"` in a downstream step silently drops all overlay
data — `$resolvedSpec` is always empty. This was the root cause of #258.

### Pub/Sub emulator: non-obvious wiring

The Upbound `provider-gcp-pubsub` (Terraform-based) performs a real OAuth2 token
exchange before any API calls, which fails against the emulator. Three pieces solve
this:

1. **`DeploymentRuntimeConfig`** (`deploy/helm-charts/asya-crossplane/templates/providers.yaml`):
   Injects `PUBSUB_EMULATOR_HOST` (and `GOOGLE_PUBSUB_CUSTOM_ENDPOINT`) into the
   provider pod so it redirects API calls to the emulator.

2. **Mock OAuth server**: Deployed when `gcpProviderConfig.emulatorHost` is set.
   The GCP credentials JSON points `token_uri` at this server to satisfy the
   mandatory token exchange.

3. **Valid RSA private key in dummy credentials**: The provider validates the key
   format even in emulator mode. `deploy.sh` embeds a real (non-functional) RSA
   key in the dummy credentials JSON — a placeholder string fails.

### `gcpProject` requirement in AsyncActor manifests

The injector sets `ASYA_PUBSUB_PROJECT_ID` on sidecar containers only if the
AsyncActor spec has a non-empty `gcpProject` field. Without it, the sidecar calls
`pubsub.NewClient(ctx, "", ...)` and crashes immediately with
`"projectID string is empty"`.

Every inline AsyncActor manifest in tests must include `gcpProject` for Pub/Sub.
The established pattern:

```python
_transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
_transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""

manifest = f"""
spec:
  transport: {_transport}{_transport_suffix}
  ...
"""
```

The `_actor_manifest()` helper handles this automatically. Only hand-crafted
manifest f-strings need the explicit `_transport_suffix` pattern.

### Test skip logic

| Test file | Skip condition | Reason |
|-----------|----------------|--------|
| `test_fanout_fanin_flow_e2e.py` | Module-level skip for non-SQS | Uses `boto3.client("sqs")` directly |
| `test_state_persistence_e2e.py` | `pytest.skip` if large payload + pubsub | Emulator can't publish multi-MB within timeout |
| `test_crossplane_e2e.py` | `if transport == "sqs": ... elif transport == "pubsub": ...` | KEDA trigger type differs |
| `test_s3_persistence_e2e.py` | Entire module skipped for pubsub | S3-specific, no GCS equivalent |

The `transport_timeouts` fixture groups SQS and Pub/Sub together with longer
timeouts — emulator gRPC pull latency is ~2x higher than SQS long-polling.

## Adding a New Transport

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

- Add emulator chart in `testing/e2e/charts/<transport>/` (`Deployment` +
  `NodePort Service` with a fixed `nodePort`)
- Add `extraPortMappings` entry in `kind-config.yaml` (shared; unused ports fine)
- Add `profiles/<transport>-<storage>.yaml` (Helm values) and
  `profiles/.env.<transport>-<storage>` (pytest env vars using `127.0.0.1:<nodePort>`)
- Add Crossplane composition `composition-<transport>.yaml` — use
  `"asya/resolved-spec"` (not `"asya.sh/resolved-spec"`) in all steps that read
  overlay data; select the correct KEDA trigger type
- Wire the injector to set transport-specific env vars on sidecar containers
- Grep existing tests for `ASYA_TRANSPORT` and `transport == "sqs"` — add new
  transport branches or skip conditions as needed
- Add the new profile to the `e2e-tests` matrix in `.github/workflows/ci.yml`
