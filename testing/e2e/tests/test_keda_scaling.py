#!/usr/bin/env python3
"""
KEDA-specific E2E tests for Asya with Crossplane architecture.

These tests require a Kind cluster with KEDA installed and verify:
1. ScaledObject creation from AsyncActor scaling spec
2. Trigger configuration (SQS queue-based autoscaling)
3. Advanced scaling parameters (pollingInterval, cooldownPeriod, etc.)
4. TriggerAuthentication for credentials
5. Cascade deletion through Crossplane
6. HPA creation by KEDA
7. Workload recovery after pod kill

With Crossplane, ScaledObjects are created as composed resources by the
Composition pipeline (not directly by the operator). The Composition
conditionally renders ScaledObject when scaling.enabled=true and the
queue URL is available from the AWS provider.
"""

import logging
import os
import subprocess
import time

import pytest

from asya_testing.utils.kubectl import (
    kubectl_apply,
    kubectl_delete,
    kubectl_get,
    log_asyncactor_workload_diagnostics,
    wait_for_asyncactor_ready,
    wait_for_deletion,
    wait_for_pod_ready,
    wait_for_resource,
)

logger = logging.getLogger(__name__)


def _cleanup_actor(name: str, namespace: str) -> None:
    """Clean up AsyncActor and all Crossplane-managed resources."""
    kubectl_delete("asyncactor", name, namespace=namespace)
    kubectl_delete("scaledobject", name, namespace=namespace)
    kubectl_delete("triggerauthentication", f"{name}-trigger-auth", namespace=namespace)
    kubectl_delete("deployment", name, namespace=namespace)
    kubectl_delete("hpa", f"keda-hpa-{name}", namespace=namespace)


@pytest.fixture(scope="module")
def ensure_keda_installed(namespace):
    """Ensure KEDA is installed in the cluster."""
    result = subprocess.run(
        ["kubectl", "get", "deployment", "-n", namespace, "keda-operator"],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"KEDA is not installed in namespace {namespace}. These tests require KEDA.")


@pytest.mark.core
@pytest.mark.timeout(300)
def test_scaledobject_created_with_scaling_enabled(ensure_keda_installed, namespace):
    """Test that ScaledObject is created when scaling.enabled=true.

    The Crossplane Composition renders a ScaledObject as a Kubernetes Object
    when the AsyncActor has scaling enabled and the queue URL is available.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-keda-basic"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 0
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        assert wait_for_resource("scaledobject", actor_name, namespace=namespace, timeout=60), \
            "ScaledObject should be created by Composition"

        scaled_obj = kubectl_get("scaledobject", actor_name, namespace=namespace)

        assert scaled_obj["spec"]["minReplicaCount"] == 0
        assert scaled_obj["spec"]["maxReplicaCount"] == 10

        triggers = scaled_obj["spec"]["triggers"]
        assert len(triggers) > 0, "ScaledObject should have at least one trigger"

        trigger = triggers[0]
        if transport == "sqs":
            assert trigger["type"] == "aws-sqs-queue"
            assert trigger["metadata"]["queueLength"] == "5"
            assert "queueURL" in trigger["metadata"]
        elif transport == "rabbitmq":
            assert trigger["type"] == "rabbitmq"

        logger.info("[+] ScaledObject created with correct configuration")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_scaledobject_not_created_when_scaling_disabled(ensure_keda_installed, namespace):
    """Test that ScaledObject is NOT created when scaling.enabled=false.

    The Composition conditionally renders ScaledObject only when scaling
    is enabled, so disabling it should result in no ScaledObject resource.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-no-scaling"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: false
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition even without scaling"

        result = subprocess.run(
            ["kubectl", "get", "scaledobject", actor_name, "-n", namespace],
            capture_output=True,
        )
        assert result.returncode != 0, "ScaledObject should NOT be created when scaling is disabled"

        logger.info("[+] ScaledObject correctly not created when scaling disabled")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_advanced_scaling_configuration(ensure_keda_installed, namespace):
    """Test that advanced scaling parameters are passed through to ScaledObject.

    The Composition maps AsyncActor scaling fields to ScaledObject spec:
    pollingInterval, cooldownPeriod, minReplicaCount, maxReplicaCount.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-advanced-scaling"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 50
    pollingInterval: 10
    cooldownPeriod: 60
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        assert wait_for_resource("scaledobject", actor_name, namespace=namespace, timeout=60), \
            "ScaledObject should be created"

        scaled_obj = kubectl_get("scaledobject", actor_name, namespace=namespace)

        assert scaled_obj["spec"]["pollingInterval"] == 10
        assert scaled_obj["spec"]["cooldownPeriod"] == 60
        assert scaled_obj["spec"]["minReplicaCount"] == 1
        assert scaled_obj["spec"]["maxReplicaCount"] == 50

        logger.info("[+] Advanced scaling configuration applied correctly")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_scaledobject_updated_on_asyncactor_change(ensure_keda_installed, namespace):
    """Test that ScaledObject is updated when AsyncActor spec changes.

    Updating the claim triggers Crossplane re-reconciliation, which
    re-renders the Composition and updates the ScaledObject.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-update-scaling"

    initial_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 0
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
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 20
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
        kubectl_apply(initial_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        initial_scaled = kubectl_get("scaledobject", actor_name, namespace=namespace)
        assert initial_scaled["spec"]["maxReplicaCount"] == 5

        kubectl_apply(updated_manifest, namespace=namespace)

        # Poll for Crossplane reconciliation (can take 30-60s)
        updated_scaled = None
        for _attempt in range(30):
            time.sleep(5)  # Poll every 5s for Crossplane reconciliation
            updated_scaled = kubectl_get("scaledobject", actor_name, namespace=namespace)
            if updated_scaled["spec"].get("minReplicaCount") == 1:
                break

        assert updated_scaled["spec"]["minReplicaCount"] == 1, \
            "ScaledObject should be updated with new minReplicas"
        assert updated_scaled["spec"]["maxReplicaCount"] == 20, \
            "ScaledObject should be updated with new maxReplicas"

        triggers = updated_scaled["spec"]["triggers"]
        if transport == "sqs":
            assert triggers[0]["metadata"]["queueLength"] == "5", \
                "Queue length trigger should be updated"

        logger.info("[+] ScaledObject updated when AsyncActor changes")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_triggerauthentication_created(ensure_keda_installed, namespace):
    """Test that TriggerAuthentication is created by the Composition.

    The Composition always creates TriggerAuthentication when scaling is
    enabled. The auth method depends on the Helm values (podIdentity or secret).
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-trigger-auth"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        trigger_auth_name = f"{actor_name}-trigger-auth"
        assert wait_for_resource("triggerauthentication", trigger_auth_name, namespace=namespace, timeout=60), \
            "TriggerAuthentication should be created by Composition"

        trigger_auth = kubectl_get("triggerauthentication", trigger_auth_name, namespace=namespace)

        spec = trigger_auth["spec"]
        if "podIdentity" in spec:
            assert spec["podIdentity"]["provider"] == "aws"
            logger.info("[+] TriggerAuthentication uses podIdentity")
        elif "secretTargetRef" in spec:
            secret_refs = spec["secretTargetRef"]
            assert len(secret_refs) > 0, "TriggerAuthentication should have secretTargetRef entries"
            param_names = {ref["parameter"] for ref in secret_refs}
            assert "awsAccessKeyID" in param_names
            assert "awsSecretAccessKey" in param_names
            logger.info("[+] TriggerAuthentication uses secret-based auth")
        else:
            pytest.fail("TriggerAuthentication should have podIdentity or secretTargetRef")

        scaled_obj = kubectl_get("scaledobject", actor_name, namespace=namespace)
        triggers = scaled_obj["spec"]["triggers"]
        assert triggers[0]["authenticationRef"]["name"] == trigger_auth_name, \
            "ScaledObject trigger should reference TriggerAuthentication"

        logger.info("[+] TriggerAuthentication created with correct configuration")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_scaledobject_cascade_deletion(ensure_keda_installed, namespace):
    """Test that ScaledObject is deleted when AsyncActor is deleted.

    Crossplane manages composed resource lifecycle: deleting the AsyncActor
    claim triggers deletion of the XR and all composed resources including
    the ScaledObject and Deployment.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-cascade-del"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        assert wait_for_resource("scaledobject", actor_name, namespace=namespace, timeout=60), \
            "ScaledObject should be created"

        kubectl_delete("asyncactor", actor_name, namespace=namespace)

        assert wait_for_deletion("scaledobject", actor_name, namespace=namespace, timeout=120), \
            "ScaledObject should be deleted when AsyncActor is removed"

        assert wait_for_deletion("deployment", actor_name, namespace=namespace, timeout=120), \
            "Deployment should be deleted when AsyncActor is removed"

        logger.info("[+] Cascade deletion completed successfully")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_hpa_created_by_keda(ensure_keda_installed, namespace):
    """Test that KEDA creates an HPA from the ScaledObject.

    KEDA watches ScaledObjects and creates a corresponding HPA with the
    configured triggers and scaling parameters.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-hpa-keda"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 1
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        assert wait_for_resource("scaledobject", actor_name, namespace=namespace, timeout=60), \
            "ScaledObject should be created"

        hpa_name = f"keda-hpa-{actor_name}"
        assert wait_for_resource("hpa", hpa_name, namespace=namespace, timeout=60), \
            "HPA should be created by KEDA from ScaledObject"

        hpa = kubectl_get("hpa", hpa_name, namespace=namespace)

        assert hpa["spec"]["scaleTargetRef"]["name"] == actor_name
        assert hpa["spec"]["scaleTargetRef"]["kind"] == "Deployment"
        assert hpa["spec"]["minReplicas"] == 1
        assert hpa["spec"]["maxReplicas"] == 10

        logger.info("[+] HPA created by KEDA with correct configuration")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.slow
@pytest.mark.timeout(300)
def test_workload_recovers_after_pod_kill(ensure_keda_installed, namespace):
    """Test that workload recovers after pod is killed.

    With KEDA ScaledObject (minReplicas=1), the Deployment controller
    should recreate the pod after it's deleted. The AsyncActor infrastructure
    status should reflect the recovery.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-pod-kill"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        label_selector = f"asya.sh/actor={actor_name}"
        assert wait_for_pod_ready(label_selector, namespace=namespace, timeout=60), \
            "Pod should be running and ready"

        result = subprocess.run(
            ["kubectl", "delete", "pod", "-l", label_selector,
             "-n", namespace, "--wait=false"],
            capture_output=True,
        )
        assert result.returncode == 0, "Pod deletion should succeed"
        logger.info("[+] Pod killed")

        assert wait_for_pod_ready(
            label_selector,
            namespace=namespace,
            timeout=60,
        ), "New pod should be created and become ready after kill"

        logger.info("[+] Workload recovered after pod kill")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_scaledobject_has_queue_url(ensure_keda_installed, namespace):
    """Test that ScaledObject trigger contains the correct queue URL.

    The Composition only renders the ScaledObject after the SQS queue
    is created and its URL is available in the queue status. This verifies
    the queue URL is correctly passed to the ScaledObject trigger metadata.
    """
    transport = os.getenv("ASYA_TRANSPORT", "sqs")
    actor_name = "test-queue-url"

    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {transport}
  scaling:
    enabled: true
    minReplicas: 0
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
        kubectl_apply(actor_manifest, namespace=namespace)

        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=120), \
            "AsyncActor should reach Ready condition"

        assert wait_for_resource("scaledobject", actor_name, namespace=namespace, timeout=60), \
            "ScaledObject should be created"

        scaled_obj = kubectl_get("scaledobject", actor_name, namespace=namespace)
        triggers = scaled_obj["spec"]["triggers"]
        assert len(triggers) > 0

        trigger = triggers[0]
        if transport == "sqs":
            queue_url = trigger["metadata"].get("queueURL", "")
            assert queue_url, "ScaledObject trigger should have a queueURL"
            expected_queue_name = f"asya-{namespace}-{actor_name}"
            assert expected_queue_name in queue_url, \
                f"Queue URL should contain '{expected_queue_name}', got: {queue_url}"
            logger.info(f"[+] ScaledObject trigger has queue URL: {queue_url}")

        actor = kubectl_get("asyncactor", actor_name, namespace=namespace)
        actor_queue_url = actor.get("status", {}).get("queueUrl", "")
        assert actor_queue_url, "AsyncActor status should have queueUrl"
        logger.info(f"[+] AsyncActor status has queue URL: {actor_queue_url}")

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)
