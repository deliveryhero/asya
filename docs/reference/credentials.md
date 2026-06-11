---
description: "Credentials mapping: auth configuration for all components (AWS, GCP, RabbitMQ, PostgreSQL)"
---

# Credentials and Secrets Reference

How authentication works across Asya components. This page maps every
credential to the namespace it lives in, the component that uses it,
and the Helm value that configures it.

---

## Architecture Overview

```
crossplane-system/              keda/                   $NS (actor namespace)
+---------------------------+   +-------------------+   +----------------------------------+
| gcp-creds (Secret)        |   | gcp-keda-secret   |   | asya-runtime (ConfigMap)         |
|   credentials.json        |   |   credentials.json|   |   asya_runtime.py                |
|   Used by: GCP provider   |   |   Used by: KEDA   |   |   Used by: all actor pods        |
|   Auth: Pub/Sub admin     |   |   Auth: read      |   |                                  |
|                           |   |   metrics          |   | gcp-keda-secret (Secret)         |
| (or: WI on provider KSA) |   +-------------------+   |   credentials.json               |
+---------------------------+                           |   Used by: TriggerAuthentication  |
                                                        |                                  |
                                                        | asya-gateway-db (Secret)          |
                                                        |   password (pg-kv backend only)  |
                                                        |   Used by: state-proxy-mesh      |
                                                        |   (not needed for pvc-kv)        |
                                                        |                                  |
                                                        | asya-gateway-auth (Secret)        |
                                                        |   a2a-api-key                    |
                                                        |   Used by: a2a-adapter (env)     |
                                                        |                                  |
                                                        | default KSA (ServiceAccount)      |
                                                        |   annotation: iam.gke.io/gcp-sa  |
                                                        |   Used by: all actor pods (WI)   |
                                                        +----------------------------------+
```

---

## GCP Pub/Sub Transport

### Service Accounts (GCP IAM)

| GCP SA | Purpose | IAM Roles | Auth mechanism |
|--------|---------|-----------|----------------|
| `asya-crossplane` | Crossplane creates/deletes Pub/Sub topics + subscriptions | `roles/pubsub.admin` | JSON key in `crossplane-system/gcp-creds`, or WI on provider KSA |
| `asya-actor` | Actor sidecars publish/consume Pub/Sub; handlers call Vertex AI | `roles/pubsub.publisher`, `roles/pubsub.subscriber`, `roles/aiplatform.user` | GKE Workload Identity on `default` KSA in actor namespace |
| `asya-keda` | KEDA reads subscription backlog for autoscaling | `roles/monitoring.viewer`, `roles/pubsub.viewer` | JSON key in `gcp-keda-secret` |

### Kubernetes Secrets

| Secret | Namespace | Key(s) | Created by | Used by | Helm value |
|--------|-----------|--------|------------|---------|------------|
| `gcp-creds` | `crossplane-system` | `credentials.json` | Manual (`kubectl create secret`) | Crossplane GCP provider | `gcpProviderConfig.secretRef.*` |
| `gcp-keda-secret` | `$NS` (actor namespace) | `credentials.json` | Manual | KEDA `TriggerAuthentication` (per-actor, created by composition) | `pubsub.keda.secretRef.name` |
| `asya-runtime` | `$NS` | `asya_runtime.py` | `asya-crossplane` chart (ConfigMap) | All actor pods (volume mount) | Automatic |
| `asya-gateway-db` | `$NS` | `password` | Manual (pg-kv only) | state-proxy-mesh sidecar (`DB_PASSWORD` → `STATE_PROXY_PG_URL`) | `database.existingSecret` (key `database.existingSecretKey`, default `password`) |
| `asya-gateway-auth` | `$NS` | `a2a-api-key` | Manual (`openssl rand`) | a2a-adapter (`ASYA_A2A_API_KEY`) | `a2a.auth.apiKey` |

### Workload Identity Bindings

| KSA | Namespace | GCP SA | Purpose |
|-----|-----------|--------|---------|
| `default` | `$NS` | `asya-actor@PROJECT` | Actor pods authenticate to Pub/Sub without JSON keys |
| `crossplane-provider-gcp-pubsub-*` | `crossplane-system` | `asya-crossplane@PROJECT` | (Optional) Provider uses WI instead of JSON key |

Setting up WI requires two steps:

```bash
# 1. Annotate KSA
kubectl annotate serviceaccount default -n $NS \
  iam.gke.io/gcp-service-account=asya-actor@${PROJECT}.iam.gserviceaccount.com

# 2. Bind WI User role (requires gcloud auth login with IAM permissions)
gcloud iam service-accounts add-iam-policy-binding \
  asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/default]" \
  --condition=None --project=$PROJECT
```

---

## AWS SQS Transport

### IAM

| Identity | Purpose | Required Policies |
|----------|---------|-------------------|
| IRSA role for actors | Sidecars send/receive SQS | `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueUrl`, `sqs:GetQueueAttributes` |
| Crossplane AWS provider | Create/delete SQS queues | `sqs:CreateQueue`, `sqs:DeleteQueue`, `sqs:TagQueue`, `sqs:GetQueueAttributes` |

### Kubernetes Secrets

| Secret | Namespace | Key(s) | Used by | Helm value |
|--------|-----------|--------|---------|------------|
| `aws-creds` | `crossplane-system` | `credentials` (INI format) | Crossplane AWS provider | `awsProviderConfig.secretRef.*` |
| `asya-runtime` | `$NS` | `asya_runtime.py` | All actor pods | Automatic |

---

## Deploying Actors to a New Namespace

When creating actors in a namespace other than the original `$NS`, these
resources must exist in the new namespace:

| Resource | Type | Source | Purpose |
|----------|------|--------|---------|
| `asya-runtime` | ConfigMap | Copy from `$NS` | Python runtime mounted in every actor pod |
| `gcp-keda-secret` | Secret | Copy from `$NS` or create new | KEDA TriggerAuthentication reads it locally |
| `default` KSA annotation | ServiceAccount | `kubectl annotate` | WI: links pods to GCP SA |
| WI IAM binding | GCP IAM | `gcloud iam` | Allows the new namespace's KSA to impersonate the GCP SA |

```bash
NEW_NS=my-new-namespace
kubectl create namespace $NEW_NS

# Copy asya-runtime ConfigMap
kubectl -n $NS get cm asya-runtime -o json | \
  jq '.metadata = {name: "asya-runtime", namespace: "'$NEW_NS'"}' | \
  kubectl apply -f -

# Copy gcp-keda-secret
kubectl -n $NS get secret gcp-keda-secret -o json | \
  jq '.metadata = {name: "gcp-keda-secret", namespace: "'$NEW_NS'"}' | \
  kubectl apply -f -

# Annotate default KSA for Workload Identity
kubectl annotate serviceaccount default -n $NEW_NS \
  iam.gke.io/gcp-service-account=asya-actor@${PROJECT}.iam.gserviceaccount.com

# Bind WI (requires gcloud auth with IAM permissions)
gcloud iam service-accounts add-iam-policy-binding \
  asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NEW_NS}/default]" \
  --condition=None --project=$PROJECT
```

---

## Common Pitfalls

**KEDA secret must be in actor namespace, not keda namespace.**
The Crossplane composition creates a `TriggerAuthentication` in the actor namespace.
It references `gcp-keda-secret` as a local secret. If the secret is only in the `keda`
namespace, the ScaledObject will never become Ready.

**Crossplane locks `compositionRef` on first creation.**
If an AsyncActor is created before `defaultCompositionRef` is set on the XRD, it picks
up whatever composition Crossplane selects (often alphabetically). Changing the XRD
default later does NOT affect existing actors. Delete and recreate them.

**The gateway DB secret is only needed with the `pg-kv` backend.**
With `stateProxy.mesh.backend: pg-kv`, the state-proxy-mesh sidecar reads the DB
password from `database.existingSecret` (key `database.existingSecretKey`, default
`password`) as `DB_PASSWORD` and assembles the connection string itself — there is no
separate DSN secret and no init container. With the `pvc-kv` backend the gateway needs
no database and no DB secret at all.

**PostgreSQL password is set at initdb time (in-cluster PG only).**
If you run your own in-cluster PostgreSQL, it reads `POSTGRES_PASSWORD` from the secret
on first start and stores it in the PVC. If the secret is later changed, PG still uses
the old password. Fix with `ALTER USER asya WITH PASSWORD '...'` inside the running pod.

**Actor pods use WI, not JSON keys.**
The `sidecar.gcpCredsSecret` helm value mounts a secret via `envFrom`. But Kubernetes
silently drops env var names containing dots (like `sa-key.json`), so ADC falls back
to the node SA. Workload Identity bypasses this entirely. Leave `gcpCredsSecret` empty
when WI is configured.
