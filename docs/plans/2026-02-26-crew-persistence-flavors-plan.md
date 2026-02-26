# Crew Persistence Flavors Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `persistence` section to the asya-crew Helm chart that auto-generates an S3 EnvironmentConfig flavor and wires it into crew actors.

**Architecture:** One shared EnvironmentConfig provides S3 infrastructure (bucket + connector sidecar). Each crew actor references the flavor via `spec.flavors[]` and independently configures its own `ASYA_PERSISTENCE_MOUNT` env var. The flavor is infrastructure-only; it does not dictate application-level paths.

**Tech Stack:** Helm templates, Crossplane EnvironmentConfig, pytest + pyyaml for validation

**Design doc:** `docs/plans/2026-02-26-crew-persistence-flavors-design.md`

---

### Task 1: Add persistence values and helpers

**Files:**
- Modify: `deploy/helm-charts/asya-crew/values.yaml`
- Modify: `deploy/helm-charts/asya-crew/templates/_helpers.tpl`

**Step 1: Add persistence section to values.yaml**

Append before the `dlq-worker:` section (after `checkpoint-s3:` block, line ~167):

```yaml
# Persistence flavor configuration
# When enabled, creates a shared EnvironmentConfig flavor providing S3 infrastructure
# (stateProxy connector + bucket). Each crew actor sets its own ASYA_PERSISTENCE_MOUNT.
persistence:
  enabled: false
  backend: ""          # "s3" (only backend currently supported)
  mountPath: /state/checkpoints
  config:
    bucket: ""         # S3 bucket name (required when enabled)
    endpoint: ""       # custom S3 endpoint for MinIO/LocalStack (omit for AWS)
    region: ""         # AWS region (optional)
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
```

Also add `ASYA_PERSISTENCE_MOUNT: ""` to x-sink and x-sump env sections (they don't have it yet, but checkpoint-s3 already does):

In x-sink.env (line ~63):
```yaml
  env:
    ASYA_SINK_HOOKS: ""
    ASYA_PERSISTENCE_MOUNT: ""
```

In x-sump.env (line ~113):
```yaml
  env:
    ASYA_PERSISTENCE_MOUNT: ""
```

**Step 2: Add helper functions to _helpers.tpl**

Append to `deploy/helm-charts/asya-crew/templates/_helpers.tpl`:

```
{{/*
Persistence flavor name
*/}}
{{- define "asya-crew.persistence.flavorName" -}}
{{- printf "%s-persistence-%s" .Release.Name .Values.persistence.backend }}
{{- end }}

{{/*
Persistence flavor labels
*/}}
{{- define "asya-crew.persistence.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
{{- end }}
```

**Step 3: Verify chart still renders**

Run: `helm template test deploy/helm-charts/asya-crew/ --set "x-sink.transport=sqs" --set "x-sump.transport=sqs" > /dev/null`

Expected: exit 0, no errors.

**Step 4: Commit**

```bash
git add deploy/helm-charts/asya-crew/values.yaml deploy/helm-charts/asya-crew/templates/_helpers.tpl
git commit -m "feat(crew): add persistence values schema and helpers"
```

---

### Task 2: Create persistence-flavor.yaml template

**Files:**
- Create: `deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml`

**Step 1: Create the EnvironmentConfig template**

Create `deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml`:

```yaml
{{- if .Values.persistence.enabled }}
{{- if not (eq .Values.persistence.backend "s3") }}
{{- fail "persistence.backend must be 's3' (only backend currently supported)" }}
{{- end }}
{{- if not .Values.persistence.config.bucket }}
{{- fail "persistence.config.bucket is required when persistence.enabled is true" }}
{{- end }}
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: {{ include "asya-crew.persistence.flavorName" . }}
  labels:
    {{- include "asya-crew.persistence.labels" . | nindent 4 }}
    asya.sh/flavor: {{ include "asya-crew.persistence.flavorName" . }}
data:
  stateProxy:
    - name: checkpoints
      mount:
        path: {{ .Values.persistence.mountPath }}
      connector:
        image: {{ .Values.persistence.connector.image }}
        env:
          - name: STATE_BUCKET
            value: {{ .Values.persistence.config.bucket | quote }}
          {{- with .Values.persistence.config.endpoint }}
          - name: STATE_ENDPOINT
            value: {{ . | quote }}
          {{- end }}
          {{- with .Values.persistence.config.region }}
          - name: AWS_REGION
            value: {{ . | quote }}
          {{- end }}
{{- end }}
```

**Step 2: Verify template renders when persistence is enabled**

Run:
```bash
helm template test deploy/helm-charts/asya-crew/ \
  --set "x-sink.transport=sqs" \
  --set "x-sump.transport=sqs" \
  --set "persistence.enabled=true" \
  --set "persistence.backend=s3" \
  --set "persistence.config.bucket=test-bucket"
```

Expected: output includes `kind: EnvironmentConfig` with `name: test-persistence-s3`.

**Step 3: Verify template does NOT render when persistence is disabled**

Run:
```bash
helm template test deploy/helm-charts/asya-crew/ \
  --set "x-sink.transport=sqs" \
  --set "x-sump.transport=sqs" | grep -c "EnvironmentConfig"
```

Expected: `0` (no EnvironmentConfig rendered).

**Step 4: Verify fail-fast on missing bucket**

Run:
```bash
helm template test deploy/helm-charts/asya-crew/ \
  --set "x-sink.transport=sqs" \
  --set "x-sump.transport=sqs" \
  --set "persistence.enabled=true" \
  --set "persistence.backend=s3" 2>&1
```

Expected: error containing "persistence.config.bucket is required".

**Step 5: Commit**

```bash
git add deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml
git commit -m "feat(crew): add persistence EnvironmentConfig template"
```

---

### Task 3: Update actor templates with conditional flavors

**Files:**
- Modify: `deploy/helm-charts/asya-crew/templates/sink.yaml`
- Modify: `deploy/helm-charts/asya-crew/templates/sump.yaml`
- Modify: `deploy/helm-charts/asya-crew/templates/checkpoint-s3.yaml`

**Step 1: Add flavors block to sink.yaml**

In `templates/sink.yaml`, insert after `transport: {{ $sink.transport }}` (line 19) and before `{{- with $sink.sidecar }}` (line 21):

```yaml

  {{- if .Values.persistence.enabled }}
  flavors:
    - {{ include "asya-crew.persistence.flavorName" . }}
  {{- end }}
```

**Step 2: Add flavors block to sump.yaml**

Same change in `templates/sump.yaml`, insert after `transport: {{ $sump.transport }}` (line 19) and before `{{- with $sump.sidecar }}` (line 21):

```yaml

  {{- if .Values.persistence.enabled }}
  flavors:
    - {{ include "asya-crew.persistence.flavorName" . }}
  {{- end }}
```

**Step 3: Add flavors block to checkpoint-s3.yaml**

Same change in `templates/checkpoint-s3.yaml`, insert after `transport: {{ $checkpointS3.transport }}` (line 19) and before `{{- with $checkpointS3.sidecar }}` (line 21):

```yaml

  {{- if .Values.persistence.enabled }}
  flavors:
    - {{ include "asya-crew.persistence.flavorName" . }}
  {{- end }}
```

**Step 4: Verify flavors appear when persistence is enabled**

Run:
```bash
helm template test deploy/helm-charts/asya-crew/ \
  --set "x-sink.transport=sqs" \
  --set "x-sump.transport=sqs" \
  --set "checkpoint-s3.enabled=true" \
  --set "checkpoint-s3.transport=sqs" \
  --set "persistence.enabled=true" \
  --set "persistence.backend=s3" \
  --set "persistence.config.bucket=test-bucket" 2>&1 | grep -A1 "flavors:"
```

Expected: three `flavors:` blocks, each with `- test-persistence-s3`.

**Step 5: Verify flavors do NOT appear when persistence is disabled**

Run:
```bash
helm template test deploy/helm-charts/asya-crew/ \
  --set "x-sink.transport=sqs" \
  --set "x-sump.transport=sqs" 2>&1 | grep -c "flavors:"
```

Expected: `0`.

**Step 6: Commit**

```bash
git add deploy/helm-charts/asya-crew/templates/sink.yaml \
       deploy/helm-charts/asya-crew/templates/sump.yaml \
       deploy/helm-charts/asya-crew/templates/checkpoint-s3.yaml
git commit -m "feat(crew): wire persistence flavor into actor templates"
```

---

### Task 4: Helm template unit tests

**Files:**
- Create: `deploy/helm-charts/asya-crew/tests/test_persistence_flavor.py`

**Step 1: Create pytest test file**

Following the pattern in `testing/e2e/tests/test_crossplane_keda.py`, create
`deploy/helm-charts/asya-crew/tests/test_persistence_flavor.py`:

```python
"""Helm template tests for crew persistence flavor."""

import subprocess
from pathlib import Path

import pytest
import yaml

CHART_PATH = Path(__file__).parent.parent


def helm_template(**set_values: str) -> list[dict]:
    """Render Helm chart and return parsed YAML documents."""
    cmd = ["helm", "template", "test", str(CHART_PATH)]
    for key, value in set_values.items():
        cmd.extend(["--set", f"{key}={value}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")
    docs = []
    for doc in yaml.safe_load_all(result.stdout):
        if doc:
            docs.append(doc)
    return docs


def helm_template_expect_fail(**set_values: str) -> str:
    """Render Helm chart expecting failure, return stderr."""
    cmd = ["helm", "template", "test", str(CHART_PATH)]
    for key, value in set_values.items():
        cmd.extend(["--set", f"{key}={value}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0, "Expected helm template to fail"
    return result.stderr


def find_docs(docs: list[dict], kind: str) -> list[dict]:
    """Find all documents of a given kind."""
    return [d for d in docs if d.get("kind") == kind]


def find_doc(docs: list[dict], kind: str, name: str) -> dict | None:
    """Find a document by kind and name."""
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name") == name:
            return d
    return None


# -- Persistence disabled (default) --


class TestPersistenceDisabled:
    """When persistence is not enabled, no flavor resources are created."""

    @pytest.fixture()
    def docs(self):
        return helm_template(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
        })

    def test_no_environment_config(self, docs):
        assert find_docs(docs, "EnvironmentConfig") == []

    def test_no_flavors_on_sink(self, docs):
        sink = find_doc(docs, "AsyncActor", "x-sink")
        assert sink is not None
        assert "flavors" not in sink["spec"]

    def test_no_flavors_on_sump(self, docs):
        sump = find_doc(docs, "AsyncActor", "x-sump")
        assert sump is not None
        assert "flavors" not in sump["spec"]


# -- Persistence enabled --


PERSISTENCE_VALUES = {
    "x-sink.transport": "sqs",
    "x-sump.transport": "sqs",
    "checkpoint-s3.enabled": "true",
    "checkpoint-s3.transport": "sqs",
    "persistence.enabled": "true",
    "persistence.backend": "s3",
    "persistence.config.bucket": "test-bucket",
}


class TestPersistenceEnabled:
    """When persistence is enabled with S3 backend."""

    @pytest.fixture()
    def docs(self):
        return helm_template(**PERSISTENCE_VALUES)

    def test_environment_config_created(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        assert ec is not None

    def test_environment_config_labels(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        assert ec["metadata"]["labels"]["asya.sh/flavor"] == "test-persistence-s3"

    def test_state_proxy_config(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        sp = ec["data"]["stateProxy"]
        assert len(sp) == 1
        assert sp[0]["name"] == "checkpoints"
        assert sp[0]["mount"]["path"] == "/state/checkpoints"
        assert "asya-state-proxy-s3-buffered-lww" in sp[0]["connector"]["image"]

    def test_state_proxy_bucket_env(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        bucket_env = next(e for e in env if e["name"] == "STATE_BUCKET")
        assert bucket_env["value"] == "test-bucket"

    def test_sink_has_flavor(self, docs):
        sink = find_doc(docs, "AsyncActor", "x-sink")
        assert "test-persistence-s3" in sink["spec"]["flavors"]

    def test_sump_has_flavor(self, docs):
        sump = find_doc(docs, "AsyncActor", "x-sump")
        assert "test-persistence-s3" in sump["spec"]["flavors"]

    def test_checkpoint_has_flavor(self, docs):
        cp = find_doc(docs, "AsyncActor", "checkpoint-s3")
        assert "test-persistence-s3" in cp["spec"]["flavors"]


# -- Optional config --


class TestPersistenceOptionalConfig:
    """Optional endpoint and region are rendered only when set."""

    def test_endpoint_rendered_when_set(self):
        vals = {**PERSISTENCE_VALUES, "persistence.config.endpoint": "http://minio:9000"}
        docs = helm_template(**vals)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        endpoint_env = next(e for e in env if e["name"] == "STATE_ENDPOINT")
        assert endpoint_env["value"] == "http://minio:9000"

    def test_endpoint_not_rendered_when_empty(self):
        docs = helm_template(**PERSISTENCE_VALUES)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        env_names = [e["name"] for e in env]
        assert "STATE_ENDPOINT" not in env_names

    def test_region_rendered_when_set(self):
        vals = {**PERSISTENCE_VALUES, "persistence.config.region": "eu-west-1"}
        docs = helm_template(**vals)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        region_env = next(e for e in env if e["name"] == "AWS_REGION")
        assert region_env["value"] == "eu-west-1"


# -- Fail-fast validation --


class TestPersistenceValidation:
    """Fail-fast when required values are missing."""

    def test_fails_without_bucket(self):
        stderr = helm_template_expect_fail(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
            "persistence.enabled": "true",
            "persistence.backend": "s3",
        })
        assert "persistence.config.bucket is required" in stderr

    def test_fails_with_unsupported_backend(self):
        stderr = helm_template_expect_fail(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
            "persistence.enabled": "true",
            "persistence.backend": "gcs",
            "persistence.config.bucket": "test",
        })
        assert "persistence.backend must be" in stderr
```

**Step 2: Run the tests**

Run: `cd deploy/helm-charts/asya-crew && python -m pytest tests/ -v`

Expected: all tests PASS.

**Step 3: Commit**

```bash
git add deploy/helm-charts/asya-crew/tests/
git commit -m "test(crew): add helm template tests for persistence flavor"
```

---

### Task 5: Run linter and final verification

**Step 1: Run helm lint**

Run: `helm lint deploy/helm-charts/asya-crew/ --set "x-sink.transport=sqs" --set "x-sump.transport=sqs"`

Expected: `0 chart(s) linted, 0 chart(s) failed`

**Step 2: Run make lint**

Run: `make lint`

Expected: all checks pass (yamlfmt may auto-fix formatting).

**Step 3: Final commit if lint made changes**

```bash
git add -A
git commit -m "style: fix lint issues"
```
