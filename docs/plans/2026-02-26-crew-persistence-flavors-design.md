# Crew Helm Chart: Built-in Persistence Flavors

**Date**: 2026-02-26
**Task**: debt/1k5a8e

## Problem

Enabling S3 persistence for crew actors currently requires users to:
1. Manually create a Crossplane EnvironmentConfig with stateProxy configuration
2. Wire the connector image, env vars, and mount path
3. Add the flavor to each crew actor's `spec.flavors` list

This is error-prone and verbose for a common operation.

## Design

### Core Principle

The persistence flavor is an **infrastructure-level concern** - it provides an S3
bucket + connector sidecar. Each actor independently configures its own mount path
via `ASYA_PERSISTENCE_MOUNT`. The flavor does not dictate application-level paths.

### Values Schema

```yaml
persistence:
  enabled: false
  backend: ""                    # "s3" (extensible to gcs, postgresql later)
  mountPath: /state/checkpoints  # base mount for stateProxy connector
  config:
    bucket: ""                   # S3 bucket name (required when enabled)
    endpoint: ""                 # custom endpoint for MinIO/LocalStack
    region: ""                   # AWS region (optional)
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
```

### Generated EnvironmentConfig

New template `templates/persistence-flavor.yaml`:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: {{ .Release.Name }}-persistence-s3
  labels:
    asya.sh/flavor: {{ .Release.Name }}-persistence-s3
data:
  stateProxy:
    - name: checkpoints
      mount:
        path: {{ .Values.persistence.mountPath }}
      connector:
        image: {{ .Values.persistence.connector.image }}
        env:
          - name: STATE_BUCKET
            value: {{ .Values.persistence.config.bucket }}
          # endpoint/region only rendered when non-empty
```

### Actor Integration

When `persistence.enabled: true`, all three crew actor templates (sink.yaml,
sump.yaml, checkpoint-s3.yaml) automatically include the flavor in `spec.flavors[]`.

Each actor sets its own `ASYA_PERSISTENCE_MOUNT` via its existing `env` section in
values.yaml. The flavor provides the connector; the actor decides the path.

### What the Flavor Does NOT Include

- `ASYA_PERSISTENCE_MOUNT` - each actor sets this independently
- AWS credentials - handled via IRSA, pod env, or sidecar env
- Per-actor subdirectories - application-level concern

## Deliverables

- `templates/persistence-flavor.yaml` - EnvironmentConfig template
- Updated `values.yaml` with `persistence:` section
- Updated `sink.yaml`, `sump.yaml`, `checkpoint-s3.yaml` with conditional `spec.flavors`
- Updated `_helpers.tpl` with flavor name helper
- Helm template validation via `helm template` assertions
