---
title: Create transport EnvironmentConfig
status: rejected
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:287
---


Superseeded by 6lxy.

## Problem

The AsyncActor XRD exposes transport-specific infrastructure fields (`region`, `providerConfigRef` for SQS; `gcpProject` for Pub/Sub) with hardcoded defaults baked into the CRD schema. This is wrong: the XRD is a user-facing API and should know nothing about which AWS account, region, or GCP project the cluster operator has configured. Those are platform concerns, not user concerns.

Current state:

- `spec.region` — XRD field, `default: us-east-1` hardcoded in schema
- `spec.providerConfigRef` — XRD field, `default: {{ .Values.awsProviderConfig.name }}` baked in at install
- `spec.gcpProject` — XRD field, no default (already better, but still wrong layer)

RabbitMQ already does it correctly: zero transport-specific fields in the XRD. The composition reads everything from Helm values.

## Design

### Principle

Any transport-specific configuration (provider credentials reference, cloud region, GCP project) is **platform configuration**, set once per cluster by the operator. It belongs in a Crossplane `EnvironmentConfig`, not in the `AsyncActor` spec.

The `AsyncActor` spec only contains **user concerns**: which actor, which transport type, workload template, scaling policy.

### EnvironmentConfig per transport

The `asya-crossplane` Helm chart creates one `EnvironmentConfig` per enabled transport, populated from `values.yaml`:

```yaml
# Created by chart for SQS transport (templates/environmentconfig-sqs.yaml)
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: asya-sqs
data:
  awsRegion: us-east-1          # .Values.awsRegion
  awsProviderConfig: default    # .Values.awsProviderConfig.name
  awsAccountId: "000000000000"  # .Values.awsAccountId
```

```yaml
# Created by chart for Pub/Sub transport (templates/environmentconfig-pubsub.yaml)
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: asya-pubsub
data:
  gcpProject: my-gcp-project    # .Values.gcpProviderConfig.projectId
  gcpProviderConfig: default    # .Values.gcpProviderConfig.name
```

RabbitMQ has no transport-specific EnvironmentConfig — its config (host, KEDA secret) already flows correctly from Helm values through the composition.

### Composition reads from native Crossplane environment

Each transport composition adds a native `environment.environmentConfigs` reference (resolved before the pipeline runs, no extra step needed):

```yaml
# In asyncactor-sqs Composition
spec:
  environment:
    environmentConfigs:
      - type: Reference
        ref:
          name: asya-sqs    # always loaded unconditionally
  pipeline:
    - step: resolve-overlays  # user overlays unchanged
    - step: render-sqs-queue
      ...
```

Inside go-template steps, the pattern replaces the current `$xr.spec.region | default "..."`:

```
{{- $env := index .context "apiextensions.crossplane.io/environment" | default dict -}}
{{- $region := index $env "awsRegion" -}}
{{- $providerConfigRef := index $env "awsProviderConfig" -}}
```

Same pattern for the Pub/Sub composition reading `gcpProject` and `gcpProviderConfig`.

### XRD changes

Remove the following fields from `xrd-asyncactor.yaml`:

- `spec.region` — deleted entirely
- `spec.providerConfigRef` — deleted entirely
- `spec.gcpProject` — deleted entirely

The composition gets these values exclusively from the `EnvironmentConfig`. No user override at the `AsyncActor` level (one default per cluster, which is the correct topology for a shared platform).

### Platform engineer workflow

Once at cluster setup time, alongside configuring IAM/permissions:

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  --set awsRegion=eu-west-1 \
  --set awsProviderConfig.name=production-aws \
  --set awsAccountId=123456789012
```

This creates `EnvironmentConfig/asya-sqs` with those values. All actors in the cluster inherit them automatically. No per-actor configuration needed.

### Interaction with user overlays

User-specified `spec.overlays` (processed by `function-asya-overlays`) write to `asya/resolved-spec` in the pipeline context. The platform EnvironmentConfig is read via the native `apiextensions.crossplane.io/environment` context key. These are independent paths — no conflict.

## Implementation Steps

1. Add `templates/environmentconfig-sqs.yaml` to `asya-crossplane` chart
2. Add `templates/environmentconfig-pubsub.yaml` (gated on `{{ if .Values.providers.gcp.enabled }}`)
3. Update `composition-sqs.yaml`: add `spec.environment.environmentConfigs`, replace `$xr.spec.region` / `$xr.spec.providerConfigRef` / Helm-value fallbacks with env context reads
4. Update `composition-pubsub.yaml`: same for `gcpProject` / `gcpProviderConfig`
5. Update `xrd-asyncactor.yaml`: remove `region`, `providerConfigRef`, `gcpProject` fields
6. Update `values-localstack.yaml` (e2e): ensure `awsRegion`, `awsProviderConfig.name`, `awsAccountId` are set correctly (they already are)
7. Update quickstart docs and examples (no `region`/`providerConfigRef` in any AsyncActor YAML)
8. Add helm lint + unit test assertions that the EnvironmentConfig is created with correct values

## Affected Files

- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`
- `deploy/helm-charts/asya-crossplane/templates/environmentconfig-sqs.yaml` (new)
- `deploy/helm-charts/asya-crossplane/templates/environmentconfig-pubsub.yaml` (new)
- `deploy/helm-charts/asya-crossplane/values.yaml` (no change needed — fields already exist)
- `docs/quickstart/README.md`
- `examples/asyas/*.yaml`
