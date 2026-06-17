---
description: "Pause/resume setup: deploy x-pause/x-resume crew actors, configure S3 checkpoint bucket"
---

# Pause/Resume

This guide shows how to deploy and configure the pause/resume infrastructure for human-in-the-loop workflows.

## Prerequisites

- `asya-crew` Helm chart deployed
- S3-compatible storage (AWS S3, MinIO, or LocalStack)
- State proxy connector configured for your actors

## Architecture Overview

Two crew actors coordinate the pause/resume lifecycle:

- **x-pause** persists the full message to storage, writes the `x-asya-pause` VFS header, and returns the payload. The sidecar detects the header, reports `paused` to the gateway, and stops routing.
- **x-resume** loads the persisted message, merges the user's resume input into the restored payload, writes the remaining route back to VFS, and returns the merged payload. The pipeline continues from where it left off.

Both actors require access to shared persistent storage via the state proxy.

## Step 1: Configure S3 Storage

### For AWS S3

Create an S3 bucket for checkpoint storage:

```bash
aws s3 mb s3://asya-checkpoints --region us-east-1
```

Create IAM policy for x-pause and x-resume actors:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::asya-checkpoints/*"
    }
  ]
}
```

Attach the policy to the IAM role used by the crew actors' service account.

### For MinIO/LocalStack

MinIO is included in the `asya-playground` chart. The bucket is created automatically.

For manual MinIO setup:

```bash
kubectl port-forward -n asya-e2e svc/minio 9000:9000

mc alias set local http://localhost:9000 minioadmin minioadmin
mc mb local/asya-checkpoints
```

## Step 2: Configure State Proxy

The state proxy connector must be configured in your Crossplane composition or directly in actor manifests to mount S3 as `/state`.

Example state proxy configuration (embedded in AsyncActor spec):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: x-pause
spec:
  # ... other fields ...
  env:
  - name: ASYA_PERSISTENCE_MOUNT
    value: "/state"
  volumeMounts:
  - name: state
    mountPath: /state
  volumes:
  - name: state
    emptyDir: {}  # Replace with actual state proxy config
```

**Note**: The actual state proxy setup depends on your backend (S3, GCS, Redis, NATS KV). See [State Proxy Documentation](../reference/components/core-state-proxy.md) for backend-specific configuration.

## Step 3: Enable x-pause and x-resume in Helm

Add to your `asya-crew` values file:

```yaml
x-pause:
  enabled: true
  env:
    ASYA_PERSISTENCE_MOUNT: "/state"
    ASYA_PAUSE_METADATA: |
      {
        "prompt": "Review this analysis before proceeding",
        "fields": [
          {
            "name": "approved",
            "type": "boolean",
            "prompt": "Approve this analysis?"
          },
          {
            "name": "notes",
            "type": "string",
            "prompt": "Any reviewer notes?",
            "payload_key": "/review/notes"
          }
        ]
      }

x-resume:
  enabled: true
  env:
    ASYA_PERSISTENCE_MOUNT: "/state"
    ASYA_RESUME_MERGE_MODE: "shallow"  # or "deep"
```

### Environment Variables

| Variable | Actor | Required | Description |
|----------|-------|----------|-------------|
| `ASYA_PERSISTENCE_MOUNT` | Both | Yes | State proxy mount path for paused message storage |
| `ASYA_PAUSE_METADATA` | x-pause | No | JSON pause metadata (prompt + fields schema) |
| `ASYA_RESUME_MERGE_MODE` | x-resume | No | `shallow` (default) or `deep` merge of user input |

## Step 4: Deploy the Chart

```bash
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-system \
  -f crew-values.yaml \
  --wait
```

## Step 5: Verify Deployment

```bash
# Check that x-pause and x-resume pods are running
kubectl get pods -n asya-system -l asya.sh/actor=x-pause
kubectl get pods -n asya-system -l asya.sh/actor=x-resume

# Check that queues were created
kubectl get asyncactor -n asya-system x-pause
kubectl get asyncactor -n asya-system x-resume
```

## Pause Metadata Schema

Pause metadata describes what input the pause point expects. It is passed to the gateway and made available to clients so they can render appropriate input UI.

### Field Properties

| Property | Required | Default | Description |
|----------|----------|---------|-------------|
| `name` | Yes | - | Field identifier (key in resume input) |
| `type` | Yes | - | JSON type: `string`, `boolean`, `number`, `array`, `object` |
| `prompt` | No | - | Human-readable label for UI |
| `payload_key` | No | `/<name>` | `/`-separated path where value lands in restored payload |
| `required` | No | `true` | UI hint; not enforced by x-resume (planned) |
| `default` | No | `null` | UI hint; not applied by x-resume (planned) |
| `options` | No | - | Enumerated choices for multichoice inputs |

When `payload_key` is omitted, the value merges at `payload["<name>"]`. When specified, intermediate dicts are created automatically (e.g., `/review/notes` creates `payload["review"]["notes"]`).

When no fields are defined, resume input merges at the payload root via shallow dict update.

### Example Metadata

```json
{
  "prompt": "Review this analysis",
  "fields": [
    {
      "name": "approved",
      "type": "boolean",
      "prompt": "Approve?",
      "required": true
    },
    {
      "name": "feedback",
      "type": "string",
      "prompt": "Reviewer comments",
      "payload_key": "/review/feedback",
      "required": false
    }
  ]
}
```

## Route Configuration

Place `x-pause` in the route where a pause point is needed:

```yaml
# Gateway flows.yaml
flows:
- name: review_pipeline
  entrypoint: analyzer
  route_next: [x-pause, summarizer]
  description: Analyze data then pause for human review
  timeout: 120
```

A route can contain multiple pause points:

```yaml
route_next: [x-pause, step-2, x-pause, step-3]
```

Each pause persists the current state. On resume, the pipeline continues from the most recent pause point.

## Troubleshooting

### x-pause fails with "state mount not found"

Check that `ASYA_PERSISTENCE_MOUNT` is set and the volume is mounted:

```bash
kubectl describe pod -n asya-system -l asya.sh/actor=x-pause
```

### x-resume cannot find checkpoint file

Check S3 bucket permissions and verify the file was written:

```bash
# For AWS S3
aws s3 ls s3://asya-checkpoints/paused/

# For MinIO
mc ls local/asya-checkpoints/paused/
```

### Resume fails with "task not paused"

The task must be in `paused` status. Check task status via the mesh-api external
service:

```bash
curl http://asya-gateway-mesh-api.<namespace>.svc.cluster.local:8080/api/v1/mesh/<task-id>
```

---

**Using pause/resume**: To use pause/resume in your actor handlers, see [usage/guide-pause-resume.md](../usage/guide-pause-resume.md).
