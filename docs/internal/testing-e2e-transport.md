# E2E Testing: Transport Backends

How message transport (SQS, Pub/Sub, RabbitMQ) is wired into E2E tests.
Captured during PRs #251, #256, #258.

## Overview

E2E tests run against a Kind cluster with a pluggable transport profile. Each
profile pairs a message transport with a storage backend (see
[testing-e2e-state-proxy.md](testing-e2e-state-proxy.md)).

Active profiles in CI:

| Profile | Transport | Storage | Status |
|---------|-----------|---------|--------|
| `sqs-s3` | LocalStack SQS | LocalStack S3 | ✅ CI |
| `pubsub-gcs` | GCP Pub/Sub emulator | fake-gcs-server | ✅ CI |
| `rabbitmq-minio` | RabbitMQ | MinIO | ❌ disabled in CI |

## File Locations

```
testing/e2e/
├── kind-config.yaml              # Kind cluster config (port mappings for all profiles)
├── Makefile                      # make up / make trigger-tests PROFILE=sqs-s3
├── profiles/
│   ├── sqs-s3.yaml              # Helm values for sqs-s3 profile
│   ├── pubsub-gcs.yaml          # Helm values for pubsub-gcs profile
│   ├── rabbitmq-minio.yaml      # Helm values for rabbitmq-minio profile
│   ├── .env.sqs-s3              # Env vars exported to pytest (host-side)
│   ├── .env.pubsub-gcs          # Env vars exported to pytest (host-side)
│   └── .env.rabbitmq-minio
├── charts/
│   ├── helmfile.yaml.gotmpl     # Assembles infra from profiles + charts
│   ├── sqs/                     # LocalStack SQS Helm chart
│   ├── pubsub/                  # GCP Pub/Sub emulator chart
│   └── rabbitmq/                # RabbitMQ chart
├── scripts/
│   └── deploy.sh                # Cluster bootstrap + secret creation
└── tests/
    ├── conftest.py              # Transport client fixture selection
    └── test_crossplane_e2e.py   # Crossplane XRD/composition tests (transport-aware)
```

## How a Profile Works

### 1. Helm values layer (`profiles/<profile>.yaml`)

The profile YAML is the single source of truth for the entire cluster configuration.
It is passed to `helmfile` as an environment file and controls which infrastructure
releases are enabled:

```yaml
# profiles/pubsub-gcs.yaml
transport:
  sqs:
    enabled: false
  pubsub:
    enabled: true   # Deploys pubsub emulator chart

storage:
  gcs:
    enabled: true   # Deploys fake-gcs chart

actors:
  transport: pubsub  # Sets transport field in all AsyncActor manifests

crossplane:
  providers:
    aws:
      enabled: false
    gcp:
      enabled: true  # Deploys provider-gcp-pubsub + GCP ProviderConfig
```

The `helmfile.yaml.gotmpl` reads these values and conditionally deploys:
- `condition: transport.pubsub.enabled` — the Pub/Sub emulator
- `condition: storage.gcs.enabled` — the fake-gcs-server

### 2. Environment file (`.env.<profile>`)

After the cluster is up, `make trigger-tests` sources `.env.<profile>` and
runs pytest. These variables configure the test-side clients:

```bash
# .env.pubsub-gcs
ASYA_TRANSPORT=pubsub
PUBSUB_EMULATOR_HOST=127.0.0.1:30085   # NodePort → Kind → emulator pod
PUBSUB_PROJECT_ID=test-project
STORAGE_EMULATOR_HOST=http://127.0.0.1:30443
```

The `127.0.0.1` addresses work because `kind-config.yaml` includes
`extraPortMappings` that bind Kind node NodePorts to localhost:

```yaml
# kind-config.yaml (all profiles share one config)
extraPortMappings:
  - containerPort: 30566   # LocalStack SQS
    hostPort: 4566
  - containerPort: 30085   # Pub/Sub emulator
    hostPort: 8085
  - containerPort: 30443   # fake-gcs
    hostPort: 4443
```

**Important**: All ports for all profiles must be in `kind-config.yaml`, because
only one Kind cluster is created per profile and it uses the shared config.
Unused ports are harmless.

### 3. Crossplane composition

Each transport has its own Crossplane composition:
- `composition-sqs.yaml` — creates SQS queue via `provider-aws-sqs`
- `composition-pubsub.yaml` — creates Topic + Subscription via `provider-gcp-pubsub`
- `composition-rabbitmq.yaml` — creates RabbitMQ queue via `provider-kubernetes`

The composition is selected by Crossplane based on the `compositeTypeRef` labels.
The XRD (`xasyncactor`) picks the correct composition based on the `spec.transport`
field value.

## Pub/Sub-Specific Wiring

Pub/Sub required the most non-obvious plumbing to work with an emulator.

### Provider authentication workaround

The Upbound `provider-gcp-pubsub` (Terraform-based) performs a real OAuth2 token
exchange before any API calls. This fails with emulator credentials because the
emulator has no OAuth2 server.

Three pieces solve this:

1. **`DeploymentRuntimeConfig`** (`deploy/helm-charts/asya-crossplane/templates/providers.yaml`):
   Injects `PUBSUB_EMULATOR_HOST` into the provider pod's environment. Note that
   the provider ignores the standard Go SDK env var and needs `GOOGLE_PUBSUB_CUSTOM_ENDPOINT`
   instead — both are set.

2. **Mock OAuth server** (`mock-oauth` deployment): A tiny HTTP server that returns
   a dummy token, deployed when `gcpProviderConfig.emulatorHost` is set.
   The GCP credentials JSON points `token_uri` to this server.

3. **Valid RSA private key in dummy credentials**: The GCP provider validates the
   key format even in emulator mode. The dummy credentials JSON in `deploy.sh`
   includes a real (non-functional) RSA key, not just a placeholder string.
   (`scripts/deploy.sh`: `GCP_DUMMY_CREDS='{"type":"service_account",...,"private_key":"..."}'`)

### `gcpProject` in AsyncActor manifests

The injector sets `ASYA_PUBSUB_PROJECT_ID` on sidecar containers only if the
AsyncActor spec contains a non-empty `gcpProject` field. Without it, the sidecar
calls `pubsub.NewClient(ctx, "", ...)` and crashes immediately with:
`"projectID string is empty"`.

Every inline AsyncActor manifest in tests must include `gcpProject` when the
transport is Pub/Sub. The established pattern (used in `test_crossplane_e2e.py`):

```python
_transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
_transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""

manifest = f"""
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
...
spec:
  transport: {_transport}{_transport_suffix}
  ...
"""
```

The `_actor_manifest()` helper function handles this automatically for tests that
use it. Only tests with hand-crafted manifest f-strings need the `_transport_suffix`
pattern.

### Crossplane context key

The Pub/Sub composition (`composition-pubsub.yaml`) uses `function-asya-overlays`,
which writes merged overlay data to the pipeline context under key `"asya/resolved-spec"`.
Downstream steps (`render-scaledobject`, `render-deployment`) must read from the
same key.

**Bug pattern to avoid**: Using `"asya.sh/resolved-spec"` (with `.sh` suffix) as
the context key causes `$resolvedSpec` to always be empty, so EnvironmentConfig
overlay data is silently dropped. The SQS composition correctly uses `"asya/resolved-spec"`.
If you copy the SQS composition as a template for a new transport, verify both
the write key (in `function-asya-overlays` step) and all read sites use the same
string.

### KEDA trigger

SQS uses a KEDA `aws-sqs-queue` trigger type. Pub/Sub uses `gcp-pubsub`. The
KEDA authentication secret (`gcp-keda-secret`) must exist in the actor namespace
before any AsyncActor is created.

## Test Skip Logic

Many tests are SQS-specific and must be skipped for Pub/Sub:

| Test file | Skip condition | Reason |
|-----------|----------------|--------|
| `test_fanout_fanin_flow_e2e.py` | Module-level `pytestmark` skip for non-SQS | Uses `boto3.client("sqs")` directly |
| `test_state_persistence_e2e.py` | `pytest.skip` if large payload + pubsub | Emulator can't publish multi-MB within timeout |
| `test_crossplane_e2e.py` | `if transport == "sqs": ... elif transport == "pubsub": ...` | KEDA trigger type differs per transport |
| `test_s3_persistence_e2e.py` | Entire module skipped | S3-specific, no GCS equivalent |

The `transport_timeouts` fixture in `asya_testing/fixtures/transport.py` returns
longer timeouts for both `sqs` and `pubsub` (emulator gRPC pull latency is ~2x
higher than SQS long-polling).

## Adding a New Transport

1. **Add emulator chart** in `testing/e2e/charts/<transport>/` with:
   - `Deployment` + `Service` (NodePort type, fixed `nodePort`)
   - `condition: transport.<name>.enabled` in `helmfile.yaml.gotmpl`

2. **Add NodePort mapping** to `kind-config.yaml` (remember: shared across profiles,
   unused ports are harmless).

3. **Create profile files**:
   - `profiles/<transport>-<storage>.yaml` — Helm values
   - `profiles/.env.<transport>-<storage>` — pytest env vars (host-side addresses
     use `127.0.0.1:<nodePort>`)

4. **Add Crossplane composition** `composition-<transport>.yaml` with:
   - Correct managed resource types for the new provider
   - Context key `"asya/resolved-spec"` (NOT `"asya.sh/resolved-spec"`) in all
     steps that read overlay data
   - Appropriate KEDA trigger type

5. **Add transport client** in `src/asya-testing/asya_testing/clients/`:
   - Implement `TransportClient` ABC
   - Add branch to `transport_client` fixture in `fixtures/transport.py`

6. **Wire injector**: The injector must set transport-specific env vars on sidecar
   containers (e.g., project ID, endpoint, credentials secret ref). Check
   `src/asya-injector/` for existing patterns.

7. **Review skip logic** in existing tests: grep for `ASYA_TRANSPORT` and
   `transport == "sqs"` to find all places that need a new branch.

8. **Update CI matrix** (`.github/workflows/ci.yml`) — add the new profile to the
   `e2e-tests` matrix once the profile is stable.

## Crossplane Composition Pipeline

For reference, the pipeline steps in a composition (e.g., `composition-pubsub.yaml`):

```
input (XAsyncActor)
  → render-queue           # Creates Topic + Subscription managed resources
  → render-sa              # Creates ServiceAccount (for IRSA/workload identity)
  → fetch-environment-configs  # Reads EnvironmentConfigs by label selector
  → function-asya-overlays    # Merges overlays into context["asya/resolved-spec"]
  → render-scaledobject    # Reads context["asya/resolved-spec"] for KEDA config
  → render-deployment      # Reads context["asya/resolved-spec"] for container config
  → function-auto-ready    # Sets READY condition based on managed resource states
```

The context key `"asya/resolved-spec"` flows from `function-asya-overlays` through
`render-scaledobject` and `render-deployment`. All three must agree on the key name.
