#!/usr/bin/env python3
"""
Crossplane KEDA configuration tests for Asya.

These tests validate the Crossplane composition templates are correctly configured
for KEDA TriggerAuthentication and ScaledObject resources.

Note: These are configuration validation tests, not scaling behavior tests.
Actual scaling behavior is tested in test_keda_scaling.py (operator-based).
"""

import subprocess
from pathlib import Path
import yaml
import pytest

# Path to the Helm chart (relative to repo root)
REPO_ROOT = Path(__file__).parent.parent.parent.parent
CHART_PATH = REPO_ROOT / "deploy/helm-charts/asya-crossplane"


def helm_template(values_file: str | Path | None = None) -> list[dict]:
    """Render Helm chart and return parsed YAML documents."""
    cmd = ["helm", "template", "test", str(CHART_PATH)]
    if values_file:
        cmd.extend(["-f", str(values_file)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")

    docs = []
    for doc in yaml.safe_load_all(result.stdout):
        if doc:
            docs.append(doc)
    return docs


def find_composition(docs: list[dict], name: str) -> dict | None:
    """Find a Composition by name in the rendered documents."""
    for doc in docs:
        if doc.get("kind") == "Composition" and doc.get("metadata", {}).get("name") == name:
            return doc
    return None


def get_pipeline_step(composition: dict, step_name: str) -> dict | None:
    """Get a pipeline step by name from a Composition."""
    pipeline = composition.get("spec", {}).get("pipeline", [])
    for step in pipeline:
        if step.get("step") == step_name:
            return step
    return None


class TestCrossplaneHelmTemplateValidation:
    """Test that Helm templates render correctly."""

    def test_helm_template_default_values(self):
        """Test helm template renders with default values."""
        docs = helm_template()
        assert len(docs) > 0, "Should render at least one document"

        # Should have XRD and Composition
        kinds = [doc.get("kind") for doc in docs]
        assert "CompositeResourceDefinition" in kinds, "Should have XRD"
        assert "Composition" in kinds, "Should have Composition"

    def test_helm_template_localstack_values(self):
        """Test helm template renders with LocalStack values."""
        docs = helm_template(CHART_PATH / "values-localstack.yaml")
        assert len(docs) > 0, "Should render with LocalStack values"


class TestCompositionSqsKedaSteps:
    """Test the SQS Composition has correct KEDA pipeline steps."""

    @pytest.fixture
    def composition_default(self) -> dict:
        """Get the SQS composition with default values."""
        docs = helm_template()
        comp = find_composition(docs, "asyncactor-sqs")
        assert comp is not None, "asyncactor-sqs Composition should exist"
        return comp

    @pytest.fixture
    def composition_localstack(self) -> dict:
        """Get the SQS composition with LocalStack values."""
        docs = helm_template(CHART_PATH / "values-localstack.yaml")
        comp = find_composition(docs, "asyncactor-sqs")
        assert comp is not None, "asyncactor-sqs Composition should exist"
        return comp

    def test_has_keda_trigger_auth_step(self, composition_default):
        """Test composition has render-triggerauthentication pipeline step."""
        step = get_pipeline_step(composition_default, "render-triggerauthentication")
        assert step is not None, "Should have render-triggerauthentication step"

        # Verify it uses go-templating function
        assert step["functionRef"]["name"] == "function-go-templating"

    def test_has_keda_scaled_object_step(self, composition_default):
        """Test composition has render-scaledobject pipeline step."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        assert step is not None, "Should have render-scaledobject step"

        # Verify it uses go-templating function
        assert step["functionRef"]["name"] == "function-go-templating"

    def test_trigger_auth_uses_pod_identity_by_default(self, composition_default):
        """Test TriggerAuthentication uses podIdentity with default values."""
        step = get_pipeline_step(composition_default, "render-triggerauthentication")
        template = step["input"]["inline"]["template"]

        # Should contain podIdentity configuration
        assert "podIdentity:" in template, "Should use podIdentity by default"
        assert "provider: aws" in template, "Should use AWS provider for IRSA"

    def test_trigger_auth_uses_secret_with_localstack(self, composition_localstack):
        """Test TriggerAuthentication uses secretTargetRef with LocalStack values."""
        step = get_pipeline_step(composition_localstack, "render-triggerauthentication")
        template = step["input"]["inline"]["template"]

        # Should contain secretTargetRef configuration
        assert "secretTargetRef:" in template, "Should use secretTargetRef for LocalStack"
        assert "awsAccessKeyID" in template, "Should have AWS Access Key ID parameter"
        assert "awsSecretAccessKey" in template, "Should have AWS Secret Access Key parameter"

    def test_trigger_auth_has_labels(self, composition_default):
        """Test TriggerAuthentication has proper labels."""
        step = get_pipeline_step(composition_default, "render-triggerauthentication")
        template = step["input"]["inline"]["template"]

        assert "app.kubernetes.io/component: triggerauthentication" in template
        assert "app.kubernetes.io/part-of: asya" in template
        assert "app.kubernetes.io/managed-by: crossplane" in template

    def test_scaled_object_has_auth_ref(self, composition_default):
        """Test ScaledObject references TriggerAuthentication."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        # Should reference TriggerAuthentication
        assert "authenticationRef:" in template, "Should have authenticationRef"
        assert "-trigger-auth" in template, "Should reference actor's TriggerAuthentication"

    def test_scaled_object_has_sqs_trigger(self, composition_default):
        """Test ScaledObject has aws-sqs-queue trigger type."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert "type: aws-sqs-queue" in template, "Should use aws-sqs-queue trigger"
        assert "queueURL:" in template, "Should have queueURL metadata"
        assert "queueLength:" in template, "Should have queueLength metadata"
        assert "awsRegion:" in template, "Should have awsRegion metadata"

    def test_scaled_object_has_localstack_endpoint(self, composition_localstack):
        """Test ScaledObject includes awsEndpoint for LocalStack."""
        step = get_pipeline_step(composition_localstack, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert "awsEndpoint:" in template, "Should have awsEndpoint for LocalStack"
        assert "localstack" in template, "Should reference LocalStack service"

    def test_scaled_object_has_hpa_behavior(self, composition_default):
        """Test ScaledObject has HPA behavior configuration."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        # Should have HPA behavior for scale-down protection
        assert "horizontalPodAutoscalerConfig:" in template
        assert "scaleDown:" in template
        assert "stabilizationWindowSeconds: 300" in template

    def test_scaled_object_has_labels(self, composition_default):
        """Test ScaledObject has proper labels."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert "app.kubernetes.io/component: scaledobject" in template
        assert "app.kubernetes.io/part-of: asya" in template
        assert "app.kubernetes.io/managed-by: crossplane" in template

    def test_scaled_object_uses_observed_queue_url(self, composition_default):
        """Test ScaledObject gets queueURL from observed resources (not status)."""
        step = get_pipeline_step(composition_default, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        # Should get queueURL from observed.resources (prevents race conditions)
        assert '.observed.resources' in template, "Should use observed.resources for queue URL"
        assert 'sqs-queue' in template, "Should reference sqs-queue resource"

    def test_pipeline_step_order(self, composition_default):
        """Test pipeline steps are in correct order."""
        pipeline = composition_default.get("spec", {}).get("pipeline", [])
        step_names = [step.get("step") for step in pipeline]

        # SQS queue must be created before KEDA resources
        sqs_idx = step_names.index("render-sqs-queue")
        trigger_auth_idx = step_names.index("render-triggerauthentication")
        scaled_obj_idx = step_names.index("render-scaledobject")
        patch_idx = step_names.index("patch-status-and-derive-phase")

        assert sqs_idx < trigger_auth_idx, "SQS queue should be rendered before TriggerAuth"
        assert trigger_auth_idx < scaled_obj_idx, "TriggerAuth should be rendered before ScaledObject"
        assert scaled_obj_idx < patch_idx, "ScaledObject should be rendered before patch-status-and-derive-phase"


class TestValuesConfiguration:
    """Test values.yaml configuration options."""

    def test_default_keda_auth_provider(self):
        """Test default KEDA authentication provider is podIdentity."""
        with open(CHART_PATH / "values.yaml") as f:
            values = yaml.safe_load(f)

        keda = values.get("keda", {})
        assert keda.get("authProvider") == "podIdentity", \
            "Default authProvider should be podIdentity (for IRSA)"

    def test_localstack_keda_auth_provider(self):
        """Test LocalStack uses secret-based authentication."""
        with open(CHART_PATH / "values-localstack.yaml") as f:
            values = yaml.safe_load(f)

        keda = values.get("keda", {})
        assert keda.get("authProvider") == "secret", \
            "LocalStack should use secret-based authentication"

    def test_localstack_secret_configuration(self):
        """Test LocalStack secret configuration is complete."""
        with open(CHART_PATH / "values-localstack.yaml") as f:
            values = yaml.safe_load(f)

        secret_ref = values.get("keda", {}).get("secretRef", {})
        assert secret_ref.get("name") == "aws-creds", "Should use aws-creds secret"
        assert secret_ref.get("accessKeyIdKey") == "AWS_ACCESS_KEY_ID"
        assert secret_ref.get("secretAccessKeyKey") == "AWS_SECRET_ACCESS_KEY"

    def test_irsa_disabled_for_localstack(self):
        """Test IRSA is disabled for LocalStack."""
        with open(CHART_PATH / "values-localstack.yaml") as f:
            values = yaml.safe_load(f)

        irsa = values.get("irsa", {})
        assert irsa.get("enabled") is False, "IRSA should be disabled for LocalStack"
