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

import pytest
import yaml


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


def find_xrd(docs: list[dict], name: str) -> dict | None:
    """Find a CompositeResourceDefinition by name in the rendered documents."""
    for doc in docs:
        if (
            doc.get("kind") == "CompositeResourceDefinition"
            and doc.get("metadata", {}).get("name") == name
        ):
            return doc
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


class TestXrdActorField:
    """Test the XRD schema has spec.actor as a required field."""

    @pytest.fixture
    def xrd(self) -> dict:
        """Get the XAsyncActor XRD."""
        docs = helm_template()
        xrd = find_xrd(docs, "xasyncactors.asya.sh")
        assert xrd is not None, "xasyncactors.asya.sh XRD should exist"
        return xrd

    @pytest.fixture
    def v1alpha1_version(self, xrd: dict) -> dict:
        """Get the v1alpha1 version definition from the XRD."""
        versions = xrd["spec"]["versions"]
        return next(v for v in versions if v["name"] == "v1alpha1")

    @pytest.fixture
    def spec_schema(self, v1alpha1_version: dict) -> dict:
        """Extract spec schema from the v1alpha1 version."""
        return v1alpha1_version["schema"]["openAPIV3Schema"]["properties"]["spec"]

    def test_actor_is_required(self, spec_schema):
        """Test that actor is listed in required fields."""
        required = spec_schema.get("required", [])
        assert "actor" in required, "spec.actor should be a required field"

    def test_actor_field_properties(self, spec_schema):
        """Test that actor field has correct validation constraints."""
        actor = spec_schema["properties"]["actor"]

        assert actor["type"] == "string"
        assert actor["minLength"] == 1
        assert actor["maxLength"] == 63

    def test_actor_field_pattern(self, spec_schema):
        """Test that actor field enforces DNS-compatible naming."""
        actor = spec_schema["properties"]["actor"]

        assert "pattern" in actor, "actor field should have a regex pattern"
        assert actor["pattern"] == "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"

    def test_actor_printer_column(self, v1alpha1_version):
        """Test that Actor printer column exists for kubectl output."""
        columns = v1alpha1_version.get("additionalPrinterColumns", [])
        column_names = [c["name"] for c in columns]

        assert "Actor" in column_names, "Should have Actor printer column"
        actor_col = next(c for c in columns if c["name"] == "Actor")
        assert actor_col["jsonPath"] == ".spec.actor"


class TestCompositionUsesSpecActor:
    """Test that the composition reads actor name from spec.actor."""

    @pytest.fixture
    def composition(self) -> dict:
        """Get the SQS composition."""
        docs = helm_template()
        comp = find_composition(docs, "asyncactor-sqs")
        assert comp is not None, "asyncactor-sqs Composition should exist"
        return comp

    def test_all_steps_use_spec_actor(self, composition):
        """Test that all pipeline steps resolve actor name from spec.actor."""
        pipeline = composition.get("spec", {}).get("pipeline", [])
        steps_with_templates = [
            step for step in pipeline
            if step.get("input", {}).get("inline", {}).get("template")
        ]

        for step in steps_with_templates:
            template = step["input"]["inline"]["template"]
            if "$actorName" in template:
                uses_spec_actor = "$xr.spec.actor" in template or "$xrSpec.actor" in template
                assert uses_spec_actor, \
                    f"Step '{step['step']}' should use $xr.spec.actor or $xrSpec.actor"
                assert 'asya.sh/actor") | default' not in template, \
                    f"Step '{step['step']}' should not fall back to label"

    def test_status_step_sets_actor_label(self, composition):
        """Test that patch-status step still sets asya.sh/actor label on XR."""
        step = get_pipeline_step(composition, "patch-status-and-derive-phase")
        template = step["input"]["inline"]["template"]

        assert "asya.sh/actor:" in template, \
            "Status step should set asya.sh/actor label for discoverability"


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


class TestScalingAdvancedXrdSchema:
    """Test XRD schema for spec.scaling.advanced fields."""

    @pytest.fixture
    def scaling_schema(self) -> dict:
        """Get the scaling schema from the XRD."""
        docs = helm_template()
        xrd = find_xrd(docs, "xasyncactors.asya.sh")
        assert xrd is not None
        versions = xrd["spec"]["versions"]
        v1alpha1 = next(v for v in versions if v["name"] == "v1alpha1")
        spec_props = v1alpha1["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
        return spec_props["scaling"]

    def test_advanced_field_exists(self, scaling_schema):
        """Test that scaling.advanced object is present in XRD schema."""
        assert "advanced" in scaling_schema["properties"], \
            "scaling.advanced should be defined in the XRD schema"

    def test_advanced_is_object_type(self, scaling_schema):
        """Test scaling.advanced is of type object."""
        advanced = scaling_schema["properties"]["advanced"]
        assert advanced["type"] == "object"

    def test_advanced_has_restore_to_original_replica_count(self, scaling_schema):
        """Test restoreToOriginalReplicaCount is a boolean field."""
        props = scaling_schema["properties"]["advanced"]["properties"]
        assert "restoreToOriginalReplicaCount" in props
        assert props["restoreToOriginalReplicaCount"]["type"] == "boolean"

    def test_advanced_has_formula_field(self, scaling_schema):
        """Test formula is a string field for composite metric expressions."""
        props = scaling_schema["properties"]["advanced"]["properties"]
        assert "formula" in props
        assert props["formula"]["type"] == "string"

    def test_advanced_has_target_field(self, scaling_schema):
        """Test target is a string field for composite metric target value."""
        props = scaling_schema["properties"]["advanced"]["properties"]
        assert "target" in props
        assert props["target"]["type"] == "string"

    def test_advanced_has_activation_target_field(self, scaling_schema):
        """Test activationTarget is a string field."""
        props = scaling_schema["properties"]["advanced"]["properties"]
        assert "activationTarget" in props
        assert props["activationTarget"]["type"] == "string"

    def test_advanced_has_metric_type_enum(self, scaling_schema):
        """Test metricType is an enum with valid KEDA values."""
        props = scaling_schema["properties"]["advanced"]["properties"]
        assert "metricType" in props
        metric_type = props["metricType"]
        assert metric_type["type"] == "string"
        assert set(metric_type["enum"]) == {"AverageValue", "Value", "Utilization"}

    def test_advanced_has_one_of_constraint(self, scaling_schema):
        """Test oneOf constraint enforces target is required when formula is set."""
        advanced = scaling_schema["properties"]["advanced"]
        assert "oneOf" in advanced, \
            "advanced schema should have oneOf to enforce formula+target co-requirement"

        one_of = advanced["oneOf"]
        assert len(one_of) == 2, "oneOf should have exactly 2 alternatives"

        # One branch: formula is NOT required (formula absent)
        no_formula = next(
            (b for b in one_of if "not" in b and "required" in b.get("not", {})), None
        )
        assert no_formula is not None, "oneOf should include a branch where formula is not required"
        assert "formula" in no_formula["not"]["required"]

        # Other branch: both formula and target are required
        with_formula = next(
            (b for b in one_of if "required" in b and "not" not in b), None
        )
        assert with_formula is not None, "oneOf should include a branch requiring formula+target"
        assert "formula" in with_formula["required"]
        assert "target" in with_formula["required"]


class TestScalingAdvancedCompositionTemplates:
    """Test that composition templates correctly emit scaling.advanced KEDA fields."""

    @pytest.fixture(params=["asyncactor-sqs", "asyncactor-rabbitmq"])
    def composition(self, request) -> dict:
        """Get SQS and RabbitMQ compositions (pubsub requires GCP values)."""
        docs = helm_template()
        comp = find_composition(docs, request.param)
        assert comp is not None, f"{request.param} Composition should exist"
        return comp

    def test_scaledobject_template_has_advanced_variable_extraction(self, composition):
        """Test render-scaledobject step extracts $advanced from $scaling."""
        step = get_pipeline_step(composition, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert "$advanced := dict" in template, \
            "Template should initialize $advanced variable"
        assert 'hasKey $scaling "advanced"' in template, \
            "Template should check for advanced key in scaling"
        assert "$advanced = $scaling.advanced" in template, \
            "Template should assign advanced from scaling"

    def test_scaledobject_template_has_restore_to_original_conditional(self, composition):
        """Test render-scaledobject template has restoreToOriginalReplicaCount conditional."""
        step = get_pipeline_step(composition, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert 'hasKey $advanced "restoreToOriginalReplicaCount"' in template, \
            "Template should conditionally emit restoreToOriginalReplicaCount"
        assert "restoreToOriginalReplicaCount:" in template

    def test_scaledobject_template_has_scaling_modifiers_conditional(self, composition):
        """Test render-scaledobject template emits scalingModifiers only when formula+target present."""
        step = get_pipeline_step(composition, "render-scaledobject")
        template = step["input"]["inline"]["template"]

        assert 'hasKey $advanced "formula"' in template, \
            "Template should gate scalingModifiers on formula being present"
        assert 'hasKey $advanced "target"' in template, \
            "Template should also gate on target being present (required with formula)"
        assert "scalingModifiers:" in template
        assert "formula:" in template
        assert "activationTarget:" in template
        assert "metricType:" in template
