#!/usr/bin/env python3
"""
E2E tests for AsyncActor lifecycle under Crossplane Composition + asya-injector architecture.

Tests AsyncActor behavior in a real Kubernetes environment:
- AsyncActor creation, updates, and deletion
- Sidecar injection verification (via mutating webhook)
- AsyncActor status conditions (Crossplane: Ready, Synced)
- Workload creation (Deployment)
- Broken image handling
- Deletion cascade
- Spec updates (replicas, scaling toggle)
- KEDA ScaledObject configuration
- Sidecar volume/mount verification
- Concurrent operations
- Crossplane provider resilience

These tests verify the Crossplane Composition + asya-injector webhook
behaves correctly in production scenarios.
"""

import json
import logging
import os
import subprocess
import time

import pytest

from asya_testing.utils.kubectl import (
    kubectl_apply,
    kubectl_apply_raw,
    kubectl_delete,
    kubectl_get,
    log_asyncactor_workload_diagnostics,
    wait_for_asyncactor_ready,
    wait_for_deletion,
    wait_for_resource,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRANSPORT = os.getenv("ASYA_TRANSPORT", "rabbitmq")
GCP_PROJECT = os.getenv("ASYA_PUBSUB_PROJECT_ID", "")


def _actor_manifest(
    name: str,
    namespace: str,
    *,
    scaling_enabled: bool = True,
    min_replicas: int = 1,
    max_replicas: int = 5,
    queue_length: int = 10,
    replicas: int | None = None,
    extra_containers: str = "",
    extra_runtime_env: str = "",
    image: str = "ghcr.io/deliveryhero/asya-testing:latest",
    image_pull_policy: str = "IfNotPresent",
    transport: str | None = None,
    flavors: list[str] | None = None,
    gcp_project: str | None = None,
) -> str:
    """Build an AsyncActor manifest with common defaults."""
    transport = transport or TRANSPORT

    # Pubsub transport requires gcpProject so the injector can set ASYA_PUBSUB_PROJECT_ID
    # on the sidecar. Default to the value from the test environment.
    if gcp_project is None and transport == "pubsub":
        gcp_project = GCP_PROJECT

    scaling_block = f"""\
  scaling:
    enabled: {str(scaling_enabled).lower()}
    minReplicas: {min_replicas}
    maxReplicas: {max_replicas}
    queueLength: {queue_length}"""

    if not scaling_enabled:
        scaling_block = """\
  scaling:
    enabled: false"""

    replicas_line = f"\n    replicas: {replicas}" if replicas is not None else ""

    flavors_block = ""
    if flavors:
        flavor_lines = "\n".join(f"    - {f}" for f in flavors)
        flavors_block = f"\n  flavors:\n{flavor_lines}"

    gcp_project_line = f"\n  gcpProject: {gcp_project}" if gcp_project else ""

    extra_env_block = f"\n{extra_runtime_env}" if extra_runtime_env else ""

    return f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {name}
  namespace: {namespace}
spec:
  actor: {name}
  transport: {transport}{gcp_project_line}{flavors_block}
{scaling_block}
  workload:
    kind: Deployment{replicas_line}
    template:
      spec:
        containers:
        - name: asya-runtime
          image: {image}
          imagePullPolicy: {image_pull_policy}
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler{extra_env_block}
{extra_containers}"""


def _cleanup_actor(name: str, namespace: str) -> None:
    """Best-effort cleanup of an AsyncActor and its child resources."""
    kubectl_delete("asyncactor", name, namespace=namespace)
    kubectl_delete("deployment", name, namespace=namespace)
    kubectl_delete("scaledobject", name, namespace=namespace)


def _get_pod_containers(actor_name: str, namespace: str) -> list[dict]:
    """Get container specs from the first Pod of an actor."""
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"asya.sh/actor={actor_name}",
            "-o",
            "jsonpath={.items[0].spec.containers}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def _get_pod_volumes(actor_name: str, namespace: str) -> list[dict]:
    """Get volume specs from the first Pod of an actor."""
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"asya.sh/actor={actor_name}",
            "-o",
            "jsonpath={.items[0].spec.volumes}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def _kubectl_patch(resource_type: str, name: str, patch: str, namespace: str = "asya-e2e") -> None:
    """Patch a Kubernetes resource using strategic-merge."""
    subprocess.run(
        ["kubectl", "patch", resource_type, name, "-n", namespace, "--type=merge", "-p", patch],
        capture_output=True,
        check=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Existing tests (unchanged logic, updated imports)
# ---------------------------------------------------------------------------


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_basic_lifecycle(e2e_helper):
    """
    E2E: Test basic AsyncActor lifecycle (create, verify, delete).

    Scenario:
    1. Create AsyncActor CRD
    2. Crossplane creates Deployment via Composition
    3. Injector webhook injects sidecar and runtime containers
    4. Queue created via Crossplane AWS provider
    5. ScaledObject created via Crossplane Kubernetes provider
    6. Delete AsyncActor
    7. All resources cleaned up

    Expected: Full lifecycle works without errors
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-lifecycle
  namespace: {e2e_helper.namespace}
spec:
  actor: test-lifecycle
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
    queueLength: 10
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(actor_manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready (Ready condition)...")
        assert wait_for_asyncactor_ready("test-lifecycle", namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready=True"
        )

        logger.info("Verifying sidecar injection (checking Pod, not Deployment)...")
        pods_result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                e2e_helper.namespace,
                "-l",
                "asya.sh/actor=test-lifecycle",
                "-o",
                "jsonpath={.items[0].spec.containers[*].name}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        container_names = pods_result.stdout.strip().split()

        assert "asya-sidecar" in container_names, "Sidecar should be injected by webhook"
        assert "asya-runtime" in container_names, "Runtime container should exist"

        logger.info("Verifying ScaledObject creation...")
        assert wait_for_resource("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=60), (
            "ScaledObject should be created"
        )

        logger.info("Deleting AsyncActor...")
        kubectl_delete("asyncactor", "test-lifecycle", namespace=e2e_helper.namespace)

        assert wait_for_deletion("deployment", "test-lifecycle", namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be deleted when AsyncActor is removed"
        )
        assert wait_for_deletion("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=120), (
            "ScaledObject should be deleted when AsyncActor is removed"
        )

        logger.info("[+] AsyncActor lifecycle completed successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-lifecycle", namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor("test-lifecycle", e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(450)
def test_asyncactor_update_propagates(e2e_helper):
    """
    E2E: Test AsyncActor updates propagate to workload.

    Scenario:
    1. Create AsyncActor with 1 min replica
    2. Update to 3 min replicas
    3. Crossplane updates ScaledObject
    4. Deployment scales accordingly

    Expected: Changes propagate correctly
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    initial_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-update
  namespace: {e2e_helper.namespace}
spec:
  actor: test-update
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
    queueLength: 10
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    updated_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-update
  namespace: {e2e_helper.namespace}
spec:
  actor: test-update
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating initial AsyncActor...")
        kubectl_apply(initial_manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(
            "test-update",
            namespace=e2e_helper.namespace,
            timeout=270,  # pubsub needs extra time for GCP subscription provisioning + KEDA stabilization
        ), "AsyncActor should reach Ready=True"

        initial_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
        assert initial_scaled["spec"]["minReplicaCount"] == 1

        logger.info("Updating AsyncActor...")
        kubectl_apply(updated_manifest, namespace=e2e_helper.namespace)

        # Poll for Crossplane reconciliation (can take 30-60s)
        updated_scaled = None
        for _attempt in range(30):
            time.sleep(5)  # Poll every 5s for up to 150s
            updated_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
            if updated_scaled["spec"].get("minReplicaCount") == 3:
                break
        assert updated_scaled["spec"]["minReplicaCount"] == 3, "ScaledObject should be updated with new minReplicas"
        assert updated_scaled["spec"]["maxReplicaCount"] == 10, "ScaledObject should be updated with new maxReplicas"

        triggers = updated_scaled["spec"]["triggers"]
        transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
        if transport == "rabbitmq":
            assert triggers[0]["metadata"]["value"] == "5", "Queue length trigger should be updated"
        elif transport == "sqs":
            assert triggers[0]["metadata"]["queueLength"] == "5", "Queue length trigger should be updated"
        elif transport == "pubsub":
            assert triggers[0]["metadata"]["value"] == "5", "Queue length trigger should be updated"

        logger.info("[+] AsyncActor updates propagated successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-update", namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor("test-update", e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_scaling_advanced_fields_propagate(e2e_helper):
    """
    E2E: Test that scaling.advanced fields propagate from XR into the KEDA ScaledObject.

    Scenario:
    1. Create AsyncActor with scaling.advanced (restoreToOriginalReplicaCount,
       formula, target, activationTarget, metricType)
    2. Wait for AsyncActor to reach Ready state (Crossplane composition pipeline complete)
    3. Fetch the resulting KEDA ScaledObject from the cluster
    4. Assert spec.advanced.restoreToOriginalReplicaCount is set correctly
    5. Assert spec.advanced.scalingModifiers has all formula-related fields

    This test verifies the composition correctly threads XRD fields through
    function-go-templating into the KEDA ScaledObject. KEDA behavior itself
    is covered by test_keda_scaling.py; here we only check field propagation.
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _gcp_line = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-scaling-advanced
  namespace: {e2e_helper.namespace}
spec:
  actor: test-scaling-advanced
  transport: {_transport}{_gcp_line}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
    queueLength: 5
    advanced:
      restoreToOriginalReplicaCount: true
      formula: "queue"
      target: "3"
      activationTarget: "1"
      metricType: AverageValue
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor with scaling.advanced fields...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Crossplane to create the ScaledObject...")
        # pubsub: ScaledObject is gated on subscription readiness, so we need
        # extra time compared to SQS. Use 180s matching the subscription setup window.
        assert wait_for_resource(
            "scaledobject",
            "test-scaling-advanced",
            namespace=e2e_helper.namespace,
            timeout=180,
        ), "Crossplane composition should create the KEDA ScaledObject with advanced fields"

        logger.info("Fetching ScaledObject and verifying advanced fields...")
        scaled = kubectl_get("scaledobject", "test-scaling-advanced", namespace=e2e_helper.namespace)
        advanced = scaled["spec"].get("advanced", {})

        assert advanced.get("restoreToOriginalReplicaCount") is True, \
            "ScaledObject spec.advanced.restoreToOriginalReplicaCount should be true"

        modifiers = advanced.get("scalingModifiers", {})
        assert modifiers.get("formula") == "queue", \
            "ScaledObject spec.advanced.scalingModifiers.formula should match XR spec"
        assert modifiers.get("target") == "3", \
            "ScaledObject spec.advanced.scalingModifiers.target should match XR spec"
        assert modifiers.get("activationTarget") == "1", \
            "ScaledObject spec.advanced.scalingModifiers.activationTarget should match XR spec"
        assert modifiers.get("metricType") == "AverageValue", \
            "ScaledObject spec.advanced.scalingModifiers.metricType should match XR spec"

        logger.info("[+] scaling.advanced fields correctly propagated to ScaledObject")

    except Exception:
        log_asyncactor_workload_diagnostics("test-scaling-advanced", namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor("test-scaling-advanced", e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_scaling_advanced_formula_without_target_rejected(e2e_helper):
    """
    E2E: Test that formula without target is rejected at admission (oneOf constraint).

    The XRD schema enforces: if formula is set, target is required (oneOf validation).
    kubectl apply should fail at the Kubernetes API server level before Crossplane
    ever sees the resource.

    Scenario:
    1. Attempt to create AsyncActor with scaling.advanced.formula but no target
    2. kubectl apply should fail with a validation error
    3. No AsyncActor resource should be created
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    invalid_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-advanced-no-target
  namespace: {e2e_helper.namespace}
spec:
  actor: test-advanced-no-target
  transport: {_transport}
  scaling:
    advanced:
      formula: "queue"
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Attempting to create AsyncActor with formula but no target...")
        result = kubectl_apply_raw(invalid_manifest, namespace=e2e_helper.namespace)

        assert result.returncode != 0, \
            "kubectl apply should be rejected when formula is set without target (oneOf constraint)"

        stderr = result.stderr.decode()
        logger.info(f"[+] Got expected rejection: {stderr[:300]}")

    finally:
        kubectl_delete("asyncactor", "test-advanced-no-target", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_invalid_transport(e2e_helper):
    """
    E2E: Test AsyncActor with invalid transport is rejected at admission.

    The XRD defines transport as enum: [sqs, rabbitmq], so kubectl apply
    with an unknown transport value fails at the Kubernetes API level.

    Scenario:
    1. Attempt to create AsyncActor with non-existent transport
    2. kubectl apply should fail (non-zero exit code)
    3. Error message should mention the invalid value

    Expected: Admission rejection, no resource created
    """
    invalid_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-invalid-transport
  namespace: {e2e_helper.namespace}
spec:
  actor: test-invalid-transport
  transport: nonexistent-transport
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
"""

    try:
        logger.info("Attempting to create AsyncActor with invalid transport...")
        result = kubectl_apply_raw(invalid_manifest, namespace=e2e_helper.namespace)

        assert result.returncode != 0, "kubectl apply should fail for invalid transport enum value"

        stderr = result.stderr.decode()
        logger.info(f"Admission rejection stderr: {stderr}")

        assert "nonexistent-transport" in stderr or "Unsupported value" in stderr or "Invalid value" in stderr, (
            f"Error message should reference the invalid transport value, got: {stderr}"
        )

        logger.info("[+] Invalid transport rejected at admission as expected")

    finally:
        kubectl_delete("asyncactor", "test-invalid-transport", namespace=e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(450)
def test_asyncactor_status_conditions(e2e_helper):
    """
    E2E: Test AsyncActor status conditions are updated correctly.

    Scenario:
    1. Create AsyncActor
    2. Check status conditions (Ready, Synced for Crossplane)
    3. Verify condition reasons and messages

    Expected: Status reflects actual state
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-status
  namespace: {e2e_helper.namespace}
spec:
  actor: test-status
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor conditions to be set...")
        assert wait_for_asyncactor_ready(
            "test-status",
            namespace=e2e_helper.namespace,
            timeout=270,  # pubsub needs extra time for GCP subscription provisioning + KEDA stabilization
        ), "AsyncActor should reach Ready phase"

        actor = kubectl_get("asyncactor", "test-status", namespace=e2e_helper.namespace)
        status = actor.get("status", {})

        logger.info(f"AsyncActor status: {status}")

        if "conditions" in status:
            conditions = status["conditions"]
            logger.info(f"Status conditions: {conditions}")

            condition_types = [c["type"] for c in conditions]
            logger.info(f"Condition types present: {condition_types}")

            assert len(conditions) > 0, "Should have status conditions"

        logger.info("[+] AsyncActor status conditions verified")

    except Exception:
        log_asyncactor_workload_diagnostics("test-status", namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor("test-status", e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_with_broken_image(e2e_helper):
    """
    E2E: Test AsyncActor with non-existent container image.

    Scenario:
    1. Create AsyncActor with invalid image
    2. Deployment created but pods fail to pull image
    3. AsyncActor status reflects the failure

    Expected: Graceful handling of image pull failures
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-broken-image
  namespace: {e2e_helper.namespace}
spec:
  actor: test-broken-image
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: false
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: nonexistent/broken-image:latest
          imagePullPolicy: Always
"""

    try:
        logger.info("Creating AsyncActor with broken image...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment to be created...")
        assert wait_for_resource("deployment", "test-broken-image", namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be created by Crossplane"
        )

        time.sleep(10)

        pods = subprocess.run(
            ["kubectl", "get", "pods", "-l", "asya.sh/actor=test-broken-image", "-n", e2e_helper.namespace],
            capture_output=True,
            text=True,
        )

        logger.info(f"Pods status: {pods.stdout}")

        deployment = kubectl_get("deployment", "test-broken-image", namespace=e2e_helper.namespace)
        status = deployment.get("status", {})
        available_replicas = status.get("availableReplicas", 0)

        assert available_replicas == 0, "No replicas should be available with broken image"

        logger.info("[+] Broken image handled gracefully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-broken-image", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-broken-image", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-broken-image", namespace=e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_sidecar_environment_variables(e2e_helper):
    """
    E2E: Test sidecar container has correct environment variables.

    With Crossplane architecture, the sidecar is injected by the asya-injector
    webhook rather than the operator. This test verifies that the webhook
    correctly configures sidecar env vars.

    Scenario:
    1. Create AsyncActor
    2. Verify sidecar container has required env vars:
       - ASYA_TRANSPORT
       - ASYA_ACTOR_NAME
       - Transport-specific configs

    Expected: All required env vars present
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-sidecar-env
  namespace: {e2e_helper.namespace}
spec:
  actor: test-sidecar-env
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: false
  workload:
    replicas: 1
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready (Ready condition)...")
        assert wait_for_asyncactor_ready("test-sidecar-env", namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready=True"
        )

        logger.info("Checking Pod containers (sidecar injected by webhook into Pods, not Deployment)...")
        pods_json = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                e2e_helper.namespace,
                "-l",
                "asya.sh/actor=test-sidecar-env",
                "-o",
                "jsonpath={.items[0].spec.containers}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        containers = json.loads(pods_json.stdout)
        sidecar = next((c for c in containers if c["name"] == "asya-sidecar"), None)

        assert sidecar is not None, "Sidecar container should exist (injected by webhook into Pod)"

        env_vars = {e["name"]: e.get("value", "") for e in sidecar.get("env", [])}

        logger.info(f"Sidecar env vars: {list(env_vars.keys())}")

        assert "ASYA_TRANSPORT" in env_vars, "Should have ASYA_TRANSPORT"
        assert "ASYA_ACTOR_NAME" in env_vars, "Should have ASYA_ACTOR_NAME"

        assert env_vars["ASYA_ACTOR_NAME"] == "test-sidecar-env", (
            f"Actor name should be test-sidecar-env, got {env_vars['ASYA_ACTOR_NAME']}"
        )

        logger.info("[+] Sidecar environment variables verified")

    except Exception:
        log_asyncactor_workload_diagnostics("test-sidecar-env", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-sidecar-env", namespace=e2e_helper.namespace)
        wait_for_deletion("deployment", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)
        wait_for_deletion("scaledobject", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)


@pytest.mark.core
def test_asyncactor_label_propagation(e2e_helper):
    """
    E2E: Test that AsyncActor labels are propagated to all child resources.

    Scenario:
    1. Create AsyncActor with custom labels
    2. Verify labels propagate to Deployment
    3. Verify labels propagate to Secret
    4. Verify labels propagate to ServiceAccount (if present)
    5. Verify labels propagate to ScaledObject
    6. Verify labels propagate to TriggerAuthentication
    7. Verify reserved labels are rejected

    Expected: All user labels present on child resources, operator labels preserved
    """
    _transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    _transport_suffix = f"\n  gcpProject: {GCP_PROJECT}" if _transport == "pubsub" and GCP_PROJECT else ""
    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-labels
  namespace: {e2e_helper.namespace}
  labels:
    app: example-ecommerce
    team: ml-platform
    env: test
spec:
  actor: test-labels
  transport: {_transport}{_transport_suffix}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 3
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor with custom labels...")
        kubectl_apply(actor_manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready("test-labels", namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready=True"
        )

        logger.info("Verifying Deployment labels...")
        deployment = kubectl_get("deployment", "test-labels", namespace=e2e_helper.namespace)
        deployment_labels = deployment["metadata"].get("labels", {})

        assert deployment_labels.get("app") == "example-ecommerce", (
            "Deployment should have user label 'app=example-ecommerce'"
        )
        assert deployment_labels.get("team") == "ml-platform", "Deployment should have user label 'team=ml-platform'"
        assert deployment_labels.get("env") == "test", "Deployment should have user label 'env=test'"
        assert deployment_labels.get("app.kubernetes.io/name") == "test-labels", (
            "Deployment should have operator label 'app.kubernetes.io/name'"
        )
        assert deployment_labels.get("app.kubernetes.io/component") == "actor", (
            "Deployment should have operator label 'app.kubernetes.io/component=actor'"
        )
        assert deployment_labels.get("app.kubernetes.io/part-of") == "asya", (
            "Deployment should have operator label 'app.kubernetes.io/part-of=asya'"
        )
        assert deployment_labels.get("app.kubernetes.io/managed-by") == "crossplane", (
            "Deployment should have operator label 'app.kubernetes.io/managed-by'"
        )
        logger.info("[+] Deployment labels verified")

        logger.info("Verifying Secret labels...")
        secret_name = "test-labels-transport-creds"
        try:
            secret = kubectl_get("secret", secret_name, namespace=e2e_helper.namespace)
            secret_labels = secret["metadata"].get("labels", {})

            assert secret_labels.get("app") == "example-ecommerce", (
                "Secret should have user label 'app=example-ecommerce'"
            )
            assert secret_labels.get("team") == "ml-platform", "Secret should have user label 'team=ml-platform'"
            assert secret_labels.get("env") == "test", "Secret should have user label 'env=test'"
            assert secret_labels.get("app.kubernetes.io/name") == "test-labels", (
                "Secret should have operator label 'app.kubernetes.io/name'"
            )
            assert secret_labels.get("app.kubernetes.io/component") == "transport-creds", (
                "Secret should have operator label 'app.kubernetes.io/component=transport-creds'"
            )
            assert secret_labels.get("app.kubernetes.io/part-of") == "asya", (
                "Secret should have operator label 'app.kubernetes.io/part-of=asya'"
            )
            assert secret_labels.get("app.kubernetes.io/managed-by") == "crossplane", (
                "Secret should have operator label 'app.kubernetes.io/managed-by'"
            )
            logger.info("[+] Secret labels verified")
        except subprocess.CalledProcessError:
            logger.info("Secret not found - skipping secret label verification (IRSA may be in use)")

        logger.info("Verifying ServiceAccount labels (SQS only)...")
        transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
        if transport == "sqs":
            sa_name = "asya-test-labels"
            try:
                sa = kubectl_get("serviceaccount", sa_name, namespace=e2e_helper.namespace)
                sa_labels = sa["metadata"].get("labels", {})

                assert sa_labels.get("app") == "example-ecommerce", (
                    "ServiceAccount should have user label 'app=example-ecommerce'"
                )
                assert sa_labels.get("team") == "ml-platform", (
                    "ServiceAccount should have user label 'team=ml-platform'"
                )
                assert sa_labels.get("env") == "test", "ServiceAccount should have user label 'env=test'"
                assert sa_labels.get("app.kubernetes.io/name") == "test-labels", (
                    "ServiceAccount should have operator label 'app.kubernetes.io/name'"
                )
                assert sa_labels.get("app.kubernetes.io/component") == "serviceaccount", (
                    "ServiceAccount should have operator label 'app.kubernetes.io/component=serviceaccount'"
                )
                assert sa_labels.get("app.kubernetes.io/part-of") == "asya", (
                    "ServiceAccount should have operator label 'app.kubernetes.io/part-of=asya'"
                )
                assert sa_labels.get("app.kubernetes.io/managed-by") == "crossplane", (
                    "ServiceAccount should have operator label 'app.kubernetes.io/managed-by'"
                )
                logger.info("[+] ServiceAccount labels verified")
            except subprocess.CalledProcessError:
                logger.info("ServiceAccount not found - IRSA may not be configured")
        else:
            logger.info("Skipping ServiceAccount verification (not SQS transport)")

        logger.info("Verifying ScaledObject labels...")
        scaledobject = kubectl_get("scaledobject", "test-labels", namespace=e2e_helper.namespace)
        scaledobject_labels = scaledobject["metadata"].get("labels", {})

        assert scaledobject_labels.get("app") == "example-ecommerce", (
            "ScaledObject should have user label 'app=example-ecommerce'"
        )
        assert scaledobject_labels.get("team") == "ml-platform", (
            "ScaledObject should have user label 'team=ml-platform'"
        )
        assert scaledobject_labels.get("env") == "test", "ScaledObject should have user label 'env=test'"
        assert scaledobject_labels.get("app.kubernetes.io/name") == "test-labels", (
            "ScaledObject should have operator label 'app.kubernetes.io/name'"
        )
        assert scaledobject_labels.get("app.kubernetes.io/component") == "scaledobject", (
            "ScaledObject should have operator label 'app.kubernetes.io/component=scaledobject'"
        )
        assert scaledobject_labels.get("app.kubernetes.io/part-of") == "asya", (
            "ScaledObject should have operator label 'app.kubernetes.io/part-of=asya'"
        )
        assert scaledobject_labels.get("app.kubernetes.io/managed-by") == "crossplane", (
            "ScaledObject should have operator label 'app.kubernetes.io/managed-by'"
        )
        logger.info("[+] ScaledObject labels verified")

        logger.info("Verifying TriggerAuthentication labels...")
        trigger_auth_name = "test-labels-trigger-auth"
        try:
            trigger_auth = kubectl_get("triggerauthentication", trigger_auth_name, namespace=e2e_helper.namespace)
            trigger_auth_labels = trigger_auth["metadata"].get("labels", {})

            assert trigger_auth_labels.get("app") == "example-ecommerce", (
                "TriggerAuthentication should have user label 'app=example-ecommerce'"
            )
            assert trigger_auth_labels.get("team") == "ml-platform", (
                "TriggerAuthentication should have user label 'team=ml-platform'"
            )
            assert trigger_auth_labels.get("env") == "test", "TriggerAuthentication should have user label 'env=test'"
            assert trigger_auth_labels.get("app.kubernetes.io/name") == "test-labels", (
                "TriggerAuthentication should have operator label 'app.kubernetes.io/name'"
            )
            assert trigger_auth_labels.get("app.kubernetes.io/component") == "triggerauthentication", (
                "TriggerAuthentication should have operator label 'app.kubernetes.io/component=triggerauthentication'"
            )
            assert trigger_auth_labels.get("app.kubernetes.io/part-of") == "asya", (
                "TriggerAuthentication should have operator label 'app.kubernetes.io/part-of=asya'"
            )
            assert trigger_auth_labels.get("app.kubernetes.io/managed-by") == "crossplane", (
                "TriggerAuthentication should have operator label 'app.kubernetes.io/managed-by'"
            )
            logger.info("[+] TriggerAuthentication labels verified")
        except subprocess.CalledProcessError:
            logger.info("TriggerAuthentication not found - credentials may be using pod identity")

        logger.info("Verifying ConfigMap does NOT have actor-specific labels...")
        configmap = kubectl_get("configmap", "asya-runtime", namespace=e2e_helper.namespace)
        configmap_labels = configmap["metadata"].get("labels", {})

        assert "app" not in configmap_labels, (
            "ConfigMap should NOT have actor-specific user label 'app' (shared resource)"
        )
        assert "team" not in configmap_labels, (
            "ConfigMap should NOT have actor-specific user label 'team' (shared resource)"
        )
        assert configmap_labels.get("app.kubernetes.io/name") == "asya-runtime", (
            "ConfigMap should have generic operator label 'app.kubernetes.io/name=asya-runtime'"
        )
        assert configmap_labels.get("app.kubernetes.io/component") == "asya-runtime", (
            "ConfigMap should have generic operator label 'app.kubernetes.io/component=asya-runtime'"
        )
        logger.info("[+] ConfigMap labels verified (no actor-specific labels)")

        logger.info("Verifying app.kubernetes.io/ labels from claims are filtered out...")
        # Operator labels (app.kubernetes.io/*) are managed by the composition.
        # User labels with this prefix are silently filtered to prevent conflicts.
        for label_key in deployment_labels:
            if label_key.startswith("app.kubernetes.io/"):
                assert label_key in (
                    "app.kubernetes.io/name",
                    "app.kubernetes.io/component",
                    "app.kubernetes.io/part-of",
                    "app.kubernetes.io/managed-by",
                ), f"Unexpected app.kubernetes.io/ label '{label_key}' on Deployment (should be operator-managed only)"
        logger.info("[+] No unexpected app.kubernetes.io/ labels on Deployment")

        logger.info("[+] Label propagation verified successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-labels", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-labels", namespace=e2e_helper.namespace, ignore_not_found=True)
        wait_for_deletion("deployment", "test-labels", namespace=e2e_helper.namespace, timeout=60)
        wait_for_deletion("scaledobject", "test-labels", namespace=e2e_helper.namespace, timeout=60)


# ---------------------------------------------------------------------------
# New tests: Deletion cascade (Script 02 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_deletion_cascades_all_resources(e2e_helper):
    """
    E2E: Test that deleting an AsyncActor cascades to all child resources.

    Scenario:
    1. Create AsyncActor with scaling enabled
    2. Wait for Deployment and ScaledObject to exist
    3. Delete AsyncActor
    4. Verify Deployment and ScaledObject are cleaned up via Crossplane cascade

    Expected: All child resources deleted automatically
    """
    name = "test-del-cascade"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=True)

    try:
        logger.info("Creating AsyncActor with scaling enabled...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready"
        )

        logger.info("Verifying Deployment exists...")
        assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=60), (
            "Deployment should exist"
        )

        logger.info("Verifying ScaledObject exists...")
        assert wait_for_resource("scaledobject", name, namespace=e2e_helper.namespace, timeout=60), (
            "ScaledObject should exist"
        )

        logger.info("Deleting AsyncActor...")
        kubectl_delete("asyncactor", name, namespace=e2e_helper.namespace)

        logger.info("Verifying cascade deletion of Deployment...")
        assert wait_for_deletion("deployment", name, namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be cascade-deleted"
        )

        logger.info("Verifying cascade deletion of ScaledObject...")
        assert wait_for_deletion("scaledobject", name, namespace=e2e_helper.namespace, timeout=120), (
            "ScaledObject should be cascade-deleted"
        )

        logger.info("[+] Deletion cascade verified successfully")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_deletion_after_manual_deployment_delete(e2e_helper):
    """
    E2E: Test AsyncActor deletion succeeds even if Deployment was manually deleted.

    Scenario:
    1. Create AsyncActor
    2. Wait for Deployment to be created
    3. Manually delete the Deployment
    4. Delete AsyncActor
    5. Verify no stuck resources remain

    Expected: AsyncActor deletion completes without errors
    """
    name = "test-del-orphan"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False)

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment...")
        assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be created"
        )

        logger.info("Manually deleting Deployment...")
        kubectl_delete("deployment", name, namespace=e2e_helper.namespace, ignore_not_found=False)
        assert wait_for_deletion("deployment", name, namespace=e2e_helper.namespace, timeout=60), (
            "Deployment should be deleted"
        )

        logger.info("Deleting AsyncActor after Deployment was manually removed...")
        kubectl_delete("asyncactor", name, namespace=e2e_helper.namespace)

        logger.info("Verifying AsyncActor is fully deleted...")
        assert wait_for_deletion("asyncactor", name, namespace=e2e_helper.namespace, timeout=120), (
            "AsyncActor should be deleted without getting stuck"
        )

        logger.info("[+] Deletion after manual Deployment removal succeeded")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


# ---------------------------------------------------------------------------
# New tests: Spec updates (Script 03 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_replicas_update_scaling_disabled(e2e_helper):
    """
    E2E: Test AsyncActor replica count update when scaling is disabled.

    Scenario:
    1. Create AsyncActor with scaling disabled and replicas=1
    2. Verify Deployment has 1 replica
    3. Patch AsyncActor to replicas=3
    4. Verify Deployment updates to 3 replicas

    Expected: Replica count change propagates to Deployment
    """
    name = "test-replicas"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False, replicas=1)

    try:
        logger.info("Creating AsyncActor with replicas=1, scaling disabled...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment...")
        assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be created"
        )

        deployment = kubectl_get("deployment", name, namespace=e2e_helper.namespace)
        assert deployment["spec"]["replicas"] == 1, "Initial replicas should be 1"

        logger.info("Patching AsyncActor to replicas=3...")
        _kubectl_patch("asyncactor", name, '{"spec":{"workload":{"replicas":3}}}', namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment to update...")
        for _attempt in range(30):
            time.sleep(5)  # Poll every 5s for Crossplane reconciliation
            deployment = kubectl_get("deployment", name, namespace=e2e_helper.namespace)
            if deployment["spec"]["replicas"] == 3:
                break
        assert deployment["spec"]["replicas"] == 3, (
            f"Deployment replicas should be 3, got {deployment['spec']['replicas']}"
        )

        logger.info("[+] Replica count update propagated successfully")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_scaling_toggle(e2e_helper):
    """
    E2E: Test toggling KEDA scaling on and off.

    Scenario:
    1. Create AsyncActor with scaling disabled
    2. Verify no ScaledObject exists
    3. Enable scaling via patch
    4. Verify ScaledObject is created
    5. Disable scaling via patch
    6. Verify ScaledObject is deleted

    Expected: ScaledObject lifecycle follows scaling.enabled flag
    """
    name = "test-scaling-toggle"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False)

    try:
        logger.info("Creating AsyncActor with scaling disabled...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment...")
        assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=120), (
            "Deployment should be created"
        )

        time.sleep(5)  # Brief wait to confirm ScaledObject does not appear
        result = subprocess.run(
            ["kubectl", "get", "scaledobject", name, "-n", e2e_helper.namespace],
            capture_output=True,
            timeout=5,
        )
        assert result.returncode != 0, "ScaledObject should NOT exist when scaling is disabled"

        logger.info("Enabling scaling via patch...")
        _kubectl_patch(
            "asyncactor",
            name,
            '{"spec":{"scaling":{"enabled":true,"minReplicas":1,"maxReplicas":5,"queueLength":10}}}',
            namespace=e2e_helper.namespace,
        )

        logger.info("Waiting for ScaledObject to be created...")
        assert wait_for_resource("scaledobject", name, namespace=e2e_helper.namespace, timeout=120), (
            "ScaledObject should be created when scaling is enabled"
        )

        logger.info("Disabling scaling via patch...")
        _kubectl_patch("asyncactor", name, '{"spec":{"scaling":{"enabled":false}}}', namespace=e2e_helper.namespace)

        logger.info("Waiting for ScaledObject to be deleted...")
        assert wait_for_deletion("scaledobject", name, namespace=e2e_helper.namespace, timeout=120), (
            "ScaledObject should be deleted when scaling is disabled"
        )

        logger.info("[+] Scaling toggle verified successfully")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


# ---------------------------------------------------------------------------
# New tests: KEDA ScaledObject configuration (Script 04 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.core
@pytest.mark.timeout(300)
def test_keda_scaledobject_detailed_configuration(e2e_helper):
    """
    E2E: Verify ScaledObject has correct KEDA trigger configuration.

    Scenario:
    1. Create AsyncActor with scaling enabled
    2. Verify ScaledObject trigger type matches transport
    3. Verify queueLength, minReplicaCount, maxReplicaCount
    4. Verify authenticationRef exists (for SQS)

    Expected: KEDA ScaledObject reflects AsyncActor spec accurately
    """
    name = "test-keda-config"
    manifest = _actor_manifest(
        name, e2e_helper.namespace, scaling_enabled=True, min_replicas=2, max_replicas=8, queue_length=15
    )

    try:
        logger.info("Creating AsyncActor with specific scaling config...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready"
        )

        logger.info("Verifying ScaledObject configuration...")
        scaled = kubectl_get("scaledobject", name, namespace=e2e_helper.namespace)

        assert scaled["spec"]["minReplicaCount"] == 2, (
            f"minReplicaCount should be 2, got {scaled['spec']['minReplicaCount']}"
        )
        assert scaled["spec"]["maxReplicaCount"] == 8, (
            f"maxReplicaCount should be 8, got {scaled['spec']['maxReplicaCount']}"
        )

        triggers = scaled["spec"]["triggers"]
        assert len(triggers) >= 1, "Should have at least one trigger"

        trigger = triggers[0]
        transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")

        if transport == "sqs":
            assert trigger["type"] == "aws-sqs-queue", f"Trigger type should be aws-sqs-queue, got {trigger['type']}"
            assert trigger["metadata"]["queueLength"] == "15", (
                f"queueLength should be '15', got {trigger['metadata'].get('queueLength')}"
            )
            assert "queueURL" in trigger["metadata"] or "queueName" in trigger["metadata"], (
                "SQS trigger should have queueURL or queueName"
            )
        elif transport == "rabbitmq":
            assert trigger["metadata"]["value"] == "15", (
                f"Queue length value should be '15', got {trigger['metadata'].get('value')}"
            )
        elif transport == "pubsub":
            assert trigger["type"] == "gcp-pubsub", f"Trigger type should be gcp-pubsub, got {trigger['type']}"
            assert trigger["metadata"]["value"] == "15", (
                f"Queue length value should be '15', got {trigger['metadata'].get('value')}"
            )
            assert "subscriptionName" in trigger["metadata"], "Pub/Sub trigger should have subscriptionName"

        logger.info(f"ScaledObject trigger config: {json.dumps(trigger, indent=2)}")
        logger.info("[+] KEDA ScaledObject configuration verified")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


# ---------------------------------------------------------------------------
# New tests: Sidecar injection (Script 06 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.core
@pytest.mark.timeout(300)
def test_sidecar_injection_volumes_on_pod(e2e_helper):
    """
    E2E: Verify Pod has correct volumes and volume mounts for sidecar injection.

    The asya-injector webhook injects volumes (socket-dir, tmp, asya-runtime)
    and configures volume mounts on both sidecar and runtime containers.

    Scenario:
    1. Create AsyncActor
    2. Wait for Pod to be running
    3. Verify Pod has socket-dir, tmp, asya-runtime volumes
    4. Verify sidecar container has socket-dir and tmp volume mounts
    5. Verify runtime container has socket-dir, tmp, and asya-runtime volume mounts

    Expected: All expected volumes and mounts present
    """
    name = "test-volumes"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False)

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready"
        )

        logger.info("Checking Pod volumes...")
        volumes = _get_pod_volumes(name, e2e_helper.namespace)
        volume_names = [v["name"] for v in volumes]
        logger.info(f"Pod volumes: {volume_names}")

        assert "socket-dir" in volume_names, "Pod should have socket-dir volume"
        assert "tmp" in volume_names, "Pod should have tmp volume"
        assert "asya-runtime" in volume_names, "Pod should have asya-runtime volume"

        logger.info("Checking container volume mounts...")
        containers = _get_pod_containers(name, e2e_helper.namespace)

        sidecar = next((c for c in containers if c["name"] == "asya-sidecar"), None)
        assert sidecar is not None, "Sidecar container should be injected"

        sidecar_mounts = {m["name"] for m in sidecar.get("volumeMounts", [])}
        logger.info(f"Sidecar volume mounts: {sidecar_mounts}")
        assert "socket-dir" in sidecar_mounts, "Sidecar should mount socket-dir"
        assert "tmp" in sidecar_mounts, "Sidecar should mount tmp"

        runtime = next((c for c in containers if c["name"] == "asya-runtime"), None)
        assert runtime is not None, "Runtime container should exist"

        runtime_mounts = {m["name"] for m in runtime.get("volumeMounts", [])}
        logger.info(f"Runtime volume mounts: {runtime_mounts}")
        assert "socket-dir" in runtime_mounts, "Runtime should mount socket-dir"
        assert "tmp" in runtime_mounts, "Runtime should mount tmp"
        assert "asya-runtime" in runtime_mounts, "Runtime should mount asya-runtime"

        logger.info("[+] Sidecar injection volumes verified")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_sidecar_injection_multi_container(e2e_helper):
    """
    E2E: Test sidecar injection with multiple user containers.

    Scenario:
    1. Create AsyncActor with asya-runtime + helper containers
    2. Verify Pod has 3 containers (sidecar injected by webhook)
    3. Verify all container names are correct

    Expected: Sidecar appended alongside user-defined containers
    """
    name = "test-multi-container"
    extra = """\
        - name: helper
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          command: ["sleep", "3600"]
"""
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False, extra_containers=extra)

    try:
        logger.info("Creating AsyncActor with multiple containers...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready"
        )

        logger.info("Checking Pod containers...")
        containers = _get_pod_containers(name, e2e_helper.namespace)
        container_names = [c["name"] for c in containers]
        logger.info(f"Pod containers: {container_names}")

        assert len(containers) == 3, (
            f"Pod should have 3 containers (runtime + helper + sidecar), got {len(containers)}: {container_names}"
        )
        assert "asya-sidecar" in container_names, "Sidecar should be injected"
        assert "asya-runtime" in container_names, "Runtime container should exist"
        assert "helper" in container_names, "Helper container should exist"

        logger.info("[+] Multi-container sidecar injection verified")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


# ---------------------------------------------------------------------------
# New tests: Concurrent operations (Script 07 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_concurrent_asyncactor_operations(e2e_helper):
    """
    E2E: Test concurrent AsyncActor creation and deletion.

    Scenario:
    1. Create 5 AsyncActors in parallel
    2. Wait for all to reach Ready
    3. Delete all AsyncActors
    4. Verify all resources cleaned up

    Expected: No race conditions or leaked resources
    """
    count = 5
    names = [f"test-concurrent-{i}" for i in range(count)]

    try:
        logger.info(f"Creating {count} AsyncActors...")
        for name in names:
            manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False)
            kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for all AsyncActors to be ready...")
        for name in names:
            assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
                f"AsyncActor {name} should reach Ready"
            )
        logger.info(f"[+] All {count} AsyncActors are ready")

        logger.info("Verifying all Deployments exist...")
        for name in names:
            assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=30), (
                f"Deployment {name} should exist"
            )

        logger.info("Deleting all AsyncActors...")
        for name in names:
            kubectl_delete("asyncactor", name, namespace=e2e_helper.namespace)

        logger.info("Verifying all Deployments are cleaned up...")
        for name in names:
            assert wait_for_deletion("deployment", name, namespace=e2e_helper.namespace, timeout=120), (
                f"Deployment {name} should be deleted"
            )

        logger.info(f"[+] Concurrent operations ({count} actors) completed successfully")

    except Exception:
        for name in names:
            log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        for name in names:
            _cleanup_actor(name, e2e_helper.namespace)


# ---------------------------------------------------------------------------
# New tests: Crossplane provider resilience (Script 01 equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.chaos
@pytest.mark.timeout(600)
def test_crossplane_resilience_after_provider_restart(e2e_helper):
    """
    E2E: Test that AsyncActors remain functional after Crossplane provider restart.

    Scenario:
    1. Create AsyncActor and wait for Ready
    2. Delete the provider-kubernetes pod in crossplane-system
    3. Wait for the provider pod to recover
    4. Verify AsyncActor is still Ready
    5. Verify Deployment still exists

    Expected: Crossplane provider recovers and actor remains healthy
    """
    name = "test-provider-restart"
    manifest = _actor_manifest(name, e2e_helper.namespace, scaling_enabled=False)

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should reach Ready"
        )

        logger.info("Deleting provider-kubernetes pod in crossplane-system...")
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                "crossplane-system",
                "-l",
                "pkg.crossplane.io/revision",
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        provider_pods = result.stdout.strip().split()
        logger.info(f"Found provider pods: {provider_pods}")

        for pod_name in provider_pods:
            if pod_name:
                subprocess.run(
                    ["kubectl", "delete", "pod", pod_name, "-n", "crossplane-system", "--grace-period=0", "--force"],
                    capture_output=True,
                    timeout=30,
                )
                logger.info(f"Deleted provider pod: {pod_name}")

        logger.info("Waiting for provider pod to recover...")
        time.sleep(10)  # Wait for Kubernetes to restart the pod
        for attempt in range(30):
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "crossplane-system",
                    "-l",
                    "pkg.crossplane.io/revision",
                    "-o",
                    'jsonpath={.items[?(@.status.phase=="Running")].metadata.name}',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                logger.info(f"Provider pod recovered after {(attempt + 1) * 5}s")
                break
            time.sleep(5)  # Poll every 5s for provider recovery

        logger.info("Verifying AsyncActor is still Ready...")
        assert wait_for_asyncactor_ready(name, namespace=e2e_helper.namespace, timeout=180), (
            "AsyncActor should remain Ready after provider restart"
        )

        logger.info("Verifying Deployment still exists...")
        assert wait_for_resource("deployment", name, namespace=e2e_helper.namespace, timeout=30), (
            "Deployment should still exist after provider restart"
        )

        logger.info("[+] Crossplane provider resilience verified")

    except Exception:
        log_asyncactor_workload_diagnostics(name, namespace=e2e_helper.namespace)
        raise
    finally:
        _cleanup_actor(name, e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(600)
def test_asyncactor_flavors_resolved(e2e_helper):
    """
    E2E: Test that spec.flavors are resolved and merged into the actor workload.

    Scenario 1 - Single flavor:
    1. Create actor with spec.flavors: [asya-test-actor] (no inline resources)
    2. Crossplane resolves flavor EnvironmentConfig, merges resources into spec
    3. Deployment is created with resources from the flavor

    Scenario 2 - Multiple flavors + env var override:
    1. Create actor with spec.flavors: [asya-test-actor, asya-test-env-vars]
       plus an inline env var FLAVOR_EXTRA_VAR=from-actor
    2. Actor inline spec wins over flavor: override is applied last
    3. Deployment env has FLAVOR_EXTRA_VAR=from-actor (not from-flavor)

    Scenario 3 - No flavors (backward compat):
    1. Actor without spec.flavors is created
    2. Actor still reconciles correctly without flavor EnvironmentConfig

    Expected: All three scenarios work correctly
    """
    actor_single = f"test-flavor-single-{e2e_helper.namespace[-4:]}"
    actor_multi = f"test-flavor-multi-{e2e_helper.namespace[-4:]}"
    actor_no_flavor = f"test-flavor-none-{e2e_helper.namespace[-4:]}"

    try:
        # --- Scenario 1: single flavor ---
        logger.info("Creating actor with single flavor...")
        kubectl_apply_raw(
            _actor_manifest(
                actor_single,
                e2e_helper.namespace,
                flavors=["asya-test-actor"],
            ),
            namespace=e2e_helper.namespace,
        )

        assert wait_for_asyncactor_ready(actor_single, namespace=e2e_helper.namespace, timeout=180), (
            "Flavor actor should reach Ready=True"
        )

        # Verify the Deployment has resources injected by the flavor
        deployment = kubectl_get("deployment", actor_single, namespace=e2e_helper.namespace)
        containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        runtime = next((c for c in containers if c["name"] == "asya-runtime"), None)
        assert runtime is not None, "asya-runtime container must exist"
        resources = runtime.get("resources", {})
        assert resources.get("limits", {}).get("cpu") == "200m", (
            f"Flavor should set cpu limit to 200m, got: {resources}"
        )
        assert resources.get("requests", {}).get("memory") == "64Mi", (
            f"Flavor should set memory request to 64Mi, got: {resources}"
        )
        logger.info("[+] Single flavor: resources correctly injected from flavor")

        # --- Scenario 2: multiple flavors + env var override ---
        logger.info("Creating actor with multiple flavors and env var override...")
        override_env = """\
          - name: FLAVOR_EXTRA_VAR
            value: from-actor"""
        manifest = _actor_manifest(
            actor_multi,
            e2e_helper.namespace,
            flavors=["asya-test-actor", "asya-test-env-vars"],
            extra_runtime_env=override_env,
        )
        kubectl_apply_raw(manifest, namespace=e2e_helper.namespace)

        assert wait_for_asyncactor_ready(actor_multi, namespace=e2e_helper.namespace, timeout=180), (
            "Multi-flavor actor should reach Ready=True"
        )

        deployment = kubectl_get("deployment", actor_multi, namespace=e2e_helper.namespace)
        containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        runtime = next((c for c in containers if c["name"] == "asya-runtime"), None)
        assert runtime is not None, "asya-runtime container must exist"
        env_vars = {e["name"]: e["value"] for e in runtime.get("env", [])}
        assert env_vars.get("FLAVOR_EXTRA_VAR") == "from-actor", (
            f"Inline env var should override flavor value, got: {env_vars}"
        )
        logger.info("[+] Multi-flavor: env var override correctly applied")

        # --- Scenario 3: no flavors (backward compat) ---
        logger.info("Creating actor without flavors...")
        kubectl_apply_raw(
            _actor_manifest(actor_no_flavor, e2e_helper.namespace),
            namespace=e2e_helper.namespace,
        )

        assert wait_for_asyncactor_ready(actor_no_flavor, namespace=e2e_helper.namespace, timeout=180), (
            "Non-overlaid actor should reach Ready=True (backward compat)"
        )
        logger.info("[+] No-flavor actor: backward compat confirmed")

    except Exception:
        for actor in [actor_single, actor_multi, actor_no_flavor]:
            log_asyncactor_workload_diagnostics(actor, namespace=e2e_helper.namespace)
        raise
    finally:
        for actor in [actor_single, actor_multi, actor_no_flavor]:
            _cleanup_actor(actor, e2e_helper.namespace)
