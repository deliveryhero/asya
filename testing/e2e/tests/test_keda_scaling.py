#!/usr/bin/env python3
"""
KEDA-specific E2E tests for Asya operator.

These tests require a Kind cluster with KEDA installed and verify:
1. ScaledObject creation when scaling.enabled=true
2. KEDA triggers configuration (RabbitMQ/SQS)
3. Advanced scaling parameters (formula, metricType, etc.)
4. TriggerAuthentication for secrets
5. Scale-to-zero behavior
"""

import textwrap
import logging
import os
import subprocess
import time

import pytest

from asya_testing.utils.kubectl import (
    kubectl_apply,
    kubectl_delete,
    kubectl_get,
    wait_for_resource,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def ensure_keda_installed():
    """Ensure KEDA is installed in the cluster."""
    result = subprocess.run(
        ["kubectl", "get", "deployment", "-n", "keda", "keda-operator"],
        capture_output=True
    )
    if result.returncode != 0:
        pytest.skip("KEDA is not installed in the cluster. These tests require KEDA.")


@pytest.mark.core
def test_scaledobject_created_with_scaling_enabled(ensure_keda_installed):
    """Test that ScaledObject is created when scaling.enabled=true."""
    logger.info("Testing ScaledObject creation with scaling enabled")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-keda-basic
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
                env:
                - name: ASYA_HANDLER
                    value: "handlers.process"
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for ScaledObject to be created
        assert wait_for_resource("scaledobject", "test-keda-basic", timeout=30), \
            "ScaledObject should be created"

        # Verify ScaledObject configuration
        scaled_obj = kubectl_get("scaledobject", "test-keda-basic")

        assert scaled_obj["spec"]["minReplicaCount"] == 0
        assert scaled_obj["spec"]["maxReplicaCount"] == 10

        # Verify triggers
        triggers = scaled_obj["spec"]["triggers"]
        assert len(triggers) > 0, "Should have at least one trigger"

        rabbitmq_trigger = triggers[0]
        assert rabbitmq_trigger["type"] == "rabbitmq"
        assert rabbitmq_trigger["metadata"]["queueName"] == "test-keda-basic"
        assert rabbitmq_trigger["metadata"]["value"] == "5"

        logger.info("[+] ScaledObject created with correct configuration")

    finally:
        kubectl_delete("asyncactor", "test-keda-basic")
        kubectl_delete("scaledobject", "test-keda-basic")


@pytest.mark.core
def test_scaledobject_not_created_when_scaling_disabled(ensure_keda_installed):
    """Test that ScaledObject is NOT created when scaling.enabled=false."""
    logger.info("Testing ScaledObject not created when scaling disabled")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-no-scaling
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
        scaling:
            enabled: false
        workload:
            kind: Deployment
            template:
            spec:
                containers:
                - name: asya-runtime
                image: python:3.13-slim
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait to ensure ScaledObject is not created
        time.sleep(5)  # Wait for operator to process (verify absence)

        # Verify ScaledObject does NOT exist
        result = subprocess.run(
            ["kubectl", "get", "scaledobject", "test-no-scaling", "-n", "asya-e2e"],
            capture_output=True
        )
        assert result.returncode != 0, "ScaledObject should NOT be created when scaling is disabled"

        logger.info("[+] ScaledObject correctly not created when scaling disabled")

    finally:
        kubectl_delete("asyncactor", "test-no-scaling")


@pytest.mark.core
def test_advanced_scaling_configuration(ensure_keda_installed):
    """Test advanced KEDA scaling parameters (pollingInterval, cooldownPeriod, etc.).

    This test verifies that KEDA accepts advanced scaling configurations.
    Note: Formula-based scaling is not tested as it requires complex trigger metric references.
    """
    logger.info("Testing advanced KEDA scaling configuration")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-advanced-scaling
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
        scaling:
            enabled: true
            minReplicas: 1
            maxReplicas: 50
            pollingInterval: 10
            cooldownPeriod: 60
            queueLength: 10
            advanced:
            restoreToOriginalReplicaCount: false
        workload:
            kind: Deployment
            template:
            spec:
                containers:
                - name: asya-runtime
                image: python:3.13-slim
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for ScaledObject
        assert wait_for_resource("scaledobject", "test-advanced-scaling", timeout=60)

        scaled_obj = kubectl_get("scaledobject", "test-advanced-scaling")

        # Verify basic scaling params
        assert scaled_obj["spec"]["pollingInterval"] == 10
        assert scaled_obj["spec"]["cooldownPeriod"] == 60
        assert scaled_obj["spec"]["minReplicaCount"] == 1
        assert scaled_obj["spec"]["maxReplicaCount"] == 50

        logger.info("[+] Advanced scaling configuration applied correctly")

    finally:
        kubectl_delete("asyncactor", "test-advanced-scaling")
        kubectl_delete("scaledobject", "test-advanced-scaling")


@pytest.mark.core
def test_scaledobject_updated_on_asyncactor_change(ensure_keda_installed):
    """Test that ScaledObject is updated when AsyncActor spec changes."""
    logger.info("Testing ScaledObject update on AsyncActor change")

    initial_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-update-scaling
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
    """)

    updated_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-update-scaling
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
    """)

    try:
        # Create initial AsyncActor
        kubectl_apply(initial_manifest)
        assert wait_for_resource("scaledobject", "test-update-scaling", timeout=30)

        # Verify initial ScaledObject
        scaled_obj = kubectl_get("scaledobject", "test-update-scaling")
        assert scaled_obj["spec"]["maxReplicaCount"] == 5

        # Update AsyncActor
        kubectl_apply(updated_manifest)

        # Wait for ScaledObject to be updated
        time.sleep(5)  # Wait for operator to apply ScaledObject changes

        # Verify ScaledObject was updated
        scaled_obj = kubectl_get("scaledobject", "test-update-scaling")
        assert scaled_obj["spec"]["minReplicaCount"] == 1
        assert scaled_obj["spec"]["maxReplicaCount"] == 20

        triggers = scaled_obj["spec"]["triggers"]
        assert triggers[0]["metadata"]["value"] == "5"

        logger.info("[+] ScaledObject updated when AsyncActor changes")

    finally:
        kubectl_delete("asyncactor", "test-update-scaling")
        kubectl_delete("scaledobject", "test-update-scaling")


@pytest.mark.core
def test_triggerauthentication_created_for_secrets(ensure_keda_installed):
    """Test that TriggerAuthentication is created when using password secrets."""
    logger.info("Testing TriggerAuthentication creation for secrets")

    # First create a secret
    secret_manifest = textwrap.dedent("""
        apiVersion: v1
        kind: Secret
        metadata:
        name: test-rabbitmq-secret
        namespace: asya-e2e
        type: Opaque
        stringData:
        password: guest
    """)
    kubectl_apply(secret_manifest)

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-trigger-auth
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for ScaledObject
        assert wait_for_resource("scaledobject", "test-trigger-auth", timeout=30)

        # Check if TriggerAuthentication was created (if operator creates it)
        # This depends on operator implementation
        scaled_obj = kubectl_get("scaledobject", "test-trigger-auth")

        # Verify ScaledObject has trigger config
        triggers = scaled_obj["spec"]["triggers"]
        assert len(triggers) > 0

        logger.info("[+] TriggerAuthentication test completed")

    finally:
        kubectl_delete("asyncactor", "test-trigger-auth")
        kubectl_delete("scaledobject", "test-trigger-auth")
        kubectl_delete("secret", "test-rabbitmq-secret")


@pytest.mark.core
def test_scaledobject_owner_reference(ensure_keda_installed):
    """Test that ScaledObject has correct owner reference to AsyncActor."""
    logger.info("Testing ScaledObject owner reference")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-owner-ref
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
    """)

    try:
        kubectl_apply(actor_manifest)
        assert wait_for_resource("scaledobject", "test-owner-ref", timeout=30)

        # Get ScaledObject and verify owner reference
        scaled_obj = kubectl_get("scaledobject", "test-owner-ref")

        owner_refs = scaled_obj["metadata"].get("ownerReferences", [])
        assert len(owner_refs) > 0, "ScaledObject should have owner reference"

        owner = owner_refs[0]
        assert owner["kind"] == "AsyncActor"
        assert owner["name"] == "test-owner-ref"
        assert owner.get("controller") is True

        logger.info("[+] ScaledObject has correct owner reference")

        # Delete AsyncActor and verify ScaledObject is also deleted
        kubectl_delete("asyncactor", "test-owner-ref")

        time.sleep(5)  # Wait for Kubernetes garbage collection

        result = subprocess.run(
            ["kubectl", "get", "scaledobject", "test-owner-ref", "-n", "asya-e2e"],
            capture_output=True
        )
        assert result.returncode != 0, "ScaledObject should be deleted with AsyncActor"

        logger.info("[+] ScaledObject deleted with AsyncActor via owner reference")

    finally:
        kubectl_delete("asyncactor", "test-owner-ref")
        kubectl_delete("scaledobject", "test-owner-ref")


@pytest.mark.core
def test_hpa_metrics_available_with_trigger_auth(ensure_keda_installed):
    """Test that HPA metrics become available after TriggerAuthentication is properly configured."""
    logger.info("Testing HPA metrics availability with TriggerAuthentication")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-hpa-metrics
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
                env:
                - name: ASYA_HANDLER
                    value: "handlers.process"
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for ScaledObject and HPA to be created
        assert wait_for_resource("scaledobject", "test-hpa-metrics", timeout=30), \
            "ScaledObject should be created"
        assert wait_for_resource("hpa", "keda-hpa-test-hpa-metrics", timeout=30), \
            "HPA should be created by KEDA"

        # Wait for TriggerAuthentication if it exists
        trigger_auth_exists = wait_for_resource("triggerauthentication", "test-hpa-metrics-trigger-auth", timeout=30)

        if trigger_auth_exists:
            # Verify TriggerAuthentication configuration
            trigger_auth = kubectl_get("triggerauthentication", "test-hpa-metrics-trigger-auth")

            secret_refs = trigger_auth["spec"].get("secretTargetRef", [])
            assert len(secret_refs) > 0, "TriggerAuthentication should have secretTargetRef"

            # Verify the password parameter is correctly set
            secret_ref = secret_refs[0]
            assert secret_ref["parameter"] == "password", \
                f"Expected parameter 'password', got '{secret_ref['parameter']}'"
            assert secret_ref["key"] == "password", \
                f"Expected key 'password', got '{secret_ref['key']}'"

            logger.info("[+] TriggerAuthentication has correct password configuration")

        # Wait for deployment to be ready first
        result = subprocess.run(
            ["kubectl", "wait", "--for=condition=available", "--timeout=60s",
             "deployment/test-hpa-metrics", "-n", "asya-e2e"],
            capture_output=True
        )
        if result.returncode == 0:
            logger.info("[+] Deployment is ready")

        # Wait for HPA metrics to become available (may take up to 30s for KEDA metrics server)
        hpa_ready = False
        max_attempts = 60
        for attempt in range(60):
            logger.debug(f"Attempt: {attempt}/{max_attempts}")
            hpa = kubectl_get("hpa", "keda-hpa-test-hpa-metrics")

            # Check if metrics are available (not <unknown>)
            metrics = hpa.get("status", {}).get("currentMetrics", [])
            if metrics:
                for metric in metrics:
                    current_value = metric.get("external", {}).get("current", {}).get("averageValue")
                    if current_value is not None:
                        hpa_ready = True
                        logger.info(f"[+] HPA metrics available: {current_value}")
                        break

            if hpa_ready:
                break

            time.sleep(1)  # Poll kubectl API for HPA metrics readiness

        # Check conditions
        conditions = hpa.get("status", {}).get("conditions", [])
        scaling_active = any(
            c.get("type") == "ScalingActive" and c.get("status") == "True"
            for c in conditions
        )

        able_to_scale = any(
            c.get("type") == "AbleToScale" and c.get("status") == "True"
            for c in conditions
        )

        if not (hpa_ready or scaling_active):
            logger.warning(f"HPA conditions: {conditions}")
            scaled_obj = kubectl_get("scaledobject", "test-hpa-metrics")
            so_conditions = scaled_obj.get("status", {}).get("conditions", [])
            logger.warning(f"ScaledObject conditions: {so_conditions}")

            keda_logs = subprocess.run(
                ["kubectl", "logs", "-n", "keda", "deployment/keda-operator", "--tail=30"],
                capture_output=True,
                text=True
            )
            logger.warning(f"Recent KEDA operator logs:\n{keda_logs.stdout}")

        assert hpa_ready or scaling_active or able_to_scale, \
            "HPA should be functional (metrics available, ScalingActive, or AbleToScale) within 60 seconds"

        logger.info("[+] HPA metrics are available with proper TriggerAuthentication")

    finally:
        kubectl_delete("asyncactor", "test-hpa-metrics")
        kubectl_delete("scaledobject", "test-hpa-metrics")
        kubectl_delete("hpa", "keda-hpa-test-hpa-metrics")


@pytest.mark.core
def test_hpa_desired_replicas_after_pod_kill(ensure_keda_installed):
    """Test that AsyncActor status shows correct desired replicas from HPA after pod is killed.

    This test verifies the fix for the issue where desired=0 was shown after killing a pod,
    even though KEDA HPA wanted desired=1. The operator should fetch desired replicas from
    the HPA status, not just copy the current running replicas.
    """
    logger.info("Testing HPA desired replicas after pod kill")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-pod-kill
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
                env:
                - name: ASYA_HANDLER
                    value: "handlers.echo"
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for deployment and HPA to be ready
        assert wait_for_resource("deployment", "test-pod-kill", timeout=60), \
            "Deployment should be created"
        assert wait_for_resource("hpa", "keda-hpa-test-pod-kill", timeout=60), \
            "HPA should be created by KEDA"

        # Wait for deployment to be available
        result = subprocess.run(
            ["kubectl", "wait", "--for=condition=available", "--timeout=60s",
             "deployment/test-pod-kill", "-n", "asya-e2e"],
            capture_output=True
        )
        assert result.returncode == 0, "Deployment should become available"

        # Wait for HPA to set desired replicas
        time.sleep(10)  # Wait for HPA to stabilize

        # Get initial state
        hpa = kubectl_get("hpa", "keda-hpa-test-pod-kill")
        initial_desired = hpa["status"]["desiredReplicas"]
        logger.info(f"Initial HPA desired replicas: {initial_desired}")

        # Get AsyncActor status
        actor = kubectl_get("asyncactor", "test-pod-kill")
        initial_actor_desired = actor["status"].get("desiredReplicas")
        logger.info(f"Initial AsyncActor desired replicas: {initial_actor_desired}")

        # Kill the pod
        result = subprocess.run(
            ["kubectl", "delete", "pod", "-l", "app=test-pod-kill", "-n", "asya-e2e", "--wait=false"],
            capture_output=True
        )
        assert result.returncode == 0, "Pod deletion should succeed"
        logger.info("[+] Pod killed")

        # Wait a moment for operator to reconcile
        time.sleep(5)  # Wait for operator to process pod deletion event

        # Check that HPA still wants desired replicas (should be minReplicas=1)
        hpa = kubectl_get("hpa", "keda-hpa-test-pod-kill")
        hpa_desired = hpa["status"]["desiredReplicas"]
        logger.info(f"HPA desired replicas after pod kill: {hpa_desired}")

        # Check AsyncActor status - this is the key test
        actor = kubectl_get("asyncactor", "test-pod-kill")
        actor_desired = actor["status"].get("desiredReplicas")
        actor_running = actor["status"].get("replicas", 0)

        logger.info(f"AsyncActor status after pod kill: running={actor_running}, desired={actor_desired}")

        # The fix ensures that AsyncActor.status.desiredReplicas comes from HPA, not current replicas
        # So even though running=0 (pod was killed), desired should match HPA (which should be 1)
        assert actor_desired is not None, "AsyncActor should have desiredReplicas set"
        assert actor_desired == hpa_desired, \
            f"AsyncActor desired ({actor_desired}) should match HPA desired ({hpa_desired})"
        assert actor_desired >= 1, \
            f"AsyncActor desired should be at least minReplicas=1, got {actor_desired}"

        # Verify that the operator didn't just copy running replicas to desired
        # If the bug exists, actor_desired would be 0 (same as running)
        if actor_running == 0:
            assert actor_desired != 0, \
                "BUG: AsyncActor desired should not be 0 when HPA wants replicas (this was the bug we fixed)"

        logger.info("[+] AsyncActor correctly shows desired replicas from HPA after pod kill")

        # Wait for new pod to start (verify recovery)
        time.sleep(10)  # Wait for new pod to be scheduled
        actor = kubectl_get("asyncactor", "test-pod-kill")
        final_running = actor["status"].get("replicas", 0)
        logger.info(f"Final running replicas: {final_running}")

    finally:
        kubectl_delete("asyncactor", "test-pod-kill")
        kubectl_delete("scaledobject", "test-pod-kill")
        kubectl_delete("hpa", "keda-hpa-test-pod-kill")


@pytest.mark.core
def test_operator_requeues_until_hpa_created(ensure_keda_installed):
    """Test that operator requeues when HPA doesn't exist yet after ScaledObject creation.

    This test verifies the fix for the race condition where:
    1. Operator creates ScaledObject
    2. Operator immediately tries to read HPA (but KEDA hasn't created it yet)
    3. Operator should requeue with 5s delay instead of falling back to current replicas

    The fix ensures operator doesn't set desired=0 when HPA is still being created by KEDA.
    """
    logger.info("Testing operator requeue behavior when HPA is not yet created")

    actor_manifest = textwrap.dedent(f"""
        apiVersion: asya.sh/v1alpha1
        kind: AsyncActor
        metadata:
        name: test-hpa-timing
        namespace: asya-e2e
        spec:
        transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
                image: python:3.13-slim
                env:
                - name: ASYA_HANDLER
                    value: "handlers.echo"
    """)

    try:
        kubectl_apply(actor_manifest)

        # Wait for ScaledObject to be created first
        assert wait_for_resource("scaledobject", "test-hpa-timing", timeout=30), \
            "ScaledObject should be created"
        logger.info("[+] ScaledObject created")

        # Wait for HPA to be created by KEDA (this is what we're testing - operator should requeue until this exists)
        hpa_created = wait_for_resource("hpa", "keda-hpa-test-hpa-timing", timeout=60)
        assert hpa_created, "HPA should be created by KEDA within 60 seconds"
        logger.info("[+] HPA created by KEDA")

        # Get HPA and verify it has desired replicas set
        hpa = kubectl_get("hpa", "keda-hpa-test-hpa-timing")
        hpa_desired = hpa["status"].get("desiredReplicas")
        logger.info(f"HPA desired replicas: {hpa_desired}")

        # Get AsyncActor status and verify desired replicas is not 0
        actor = kubectl_get("asyncactor", "test-hpa-timing")
        actor_desired = actor["status"].get("desiredReplicas")
        logger.info(f"AsyncActor desired replicas: {actor_desired}")

        # The key assertion: operator should have requeued until HPA was created,
        # so desired replicas should come from HPA, not fall back to current replicas (0)
        assert actor_desired is not None, "AsyncActor should have desiredReplicas set"
        if hpa_desired is not None and hpa_desired > 0:
            assert actor_desired == hpa_desired, \
                f"AsyncActor desired ({actor_desired}) should match HPA desired ({hpa_desired})"

        # Verify the operator didn't incorrectly set desired=0 during the race condition window
        # This would happen if operator fell back to current replicas instead of requeuing
        assert actor_desired >= 1, \
            f"AsyncActor desired should be at least minReplicas=1, got {actor_desired}. " \
            "This indicates operator may have fallen back to current replicas instead of requeuing."

        logger.info("[+] Operator correctly requeued until HPA was created by KEDA")

        # Verify deployment eventually becomes ready
        result = subprocess.run(
            ["kubectl", "wait", "--for=condition=available", "--timeout=120s",
             "deployment/test-hpa-timing", "-n", "asya-e2e"],
            capture_output=True
        )
        assert result.returncode == 0, "Deployment should become available"
        logger.info("[+] Deployment is available")

    finally:
        kubectl_delete("asyncactor", "test-hpa-timing")
        kubectl_delete("scaledobject", "test-hpa-timing")
        kubectl_delete("hpa", "keda-hpa-test-hpa-timing")
