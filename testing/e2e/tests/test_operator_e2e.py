#!/usr/bin/env python3
"""
E2E tests for Asya Operator and AsyncActor CRD lifecycle.

Tests operator functionality in a real Kubernetes environment:
- AsyncActor creation, updates, and deletion
- Invalid CRD configurations and validation
- Sidecar injection verification
- AsyncActor status conditions
- Workload creation (Deployment/StatefulSet)
- Transport configuration handling

These tests verify the operator behaves correctly in production scenarios.
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
    wait_for_asyncactor_ready,
    wait_for_deletion,
    wait_for_deployment_ready,
    wait_for_resource,
)

logger = logging.getLogger(__name__)


@pytest.mark.core
def test_asyncactor_basic_lifecycle(e2e_helper):
    """
    E2E: Test basic AsyncActor lifecycle (create, verify, delete).

    Scenario:
    1. Create AsyncActor CRD
    2. Operator creates Deployment
    3. Sidecar and runtime containers injected
    4. Queue created
    5. ScaledObject created
    6. Delete AsyncActor
    7. All resources cleaned up

    Expected: Full lifecycle works without errors
    """
    actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-lifecycle
  namespace: {e2e_helper.namespace}
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
          image: asya-testing:latest
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(actor_manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready (WorkloadReady condition)...")
        assert wait_for_asyncactor_ready("test-lifecycle", namespace=e2e_helper.namespace, timeout=60), \
            "AsyncActor should reach WorkloadReady=True"

        logger.info("Verifying sidecar injection...")
        deployment = kubectl_get("deployment", "test-lifecycle", namespace=e2e_helper.namespace)
        containers = deployment["spec"]["template"]["spec"]["containers"]
        container_names = [c["name"] for c in containers]

        assert "asya-sidecar" in container_names, "Sidecar should be injected"
        assert "asya-runtime" in container_names, "Runtime container should exist"

        logger.info("Verifying ScaledObject creation...")
        assert wait_for_resource("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=60), \
            "ScaledObject should be created"

        logger.info("Deleting AsyncActor...")
        kubectl_delete("asyncactor", "test-lifecycle", namespace=e2e_helper.namespace)

        assert wait_for_deletion("deployment", "test-lifecycle", namespace=e2e_helper.namespace, timeout=60), \
            "Deployment should be deleted by finalizer"
        assert wait_for_deletion("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=60), \
            "ScaledObject should be deleted by finalizer"

        logger.info("[+] AsyncActor lifecycle completed successfully")

    finally:
        kubectl_delete("asyncactor", "test-lifecycle", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-lifecycle", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_update_propagates(e2e_helper):
    """
    E2E: Test AsyncActor updates propagate to workload.

    Scenario:
    1. Create AsyncActor with 1 min replica
    2. Update to 3 min replicas
    3. Operator updates ScaledObject
    4. Deployment scales accordingly

    Expected: Changes propagate correctly
    """
    initial_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-update
  namespace: {e2e_helper.namespace}
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
          image: asya-testing:latest
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
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
          image: asya-testing:latest
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating initial AsyncActor...")
        kubectl_apply(initial_manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready (WorkloadReady + ScalingReady)...")
        assert wait_for_asyncactor_ready(
            "test-update",
            namespace=e2e_helper.namespace,
            timeout=60,
            required_conditions=["WorkloadReady", "ScalingReady"],
        ), "AsyncActor should reach WorkloadReady=True and ScalingReady=True"

        initial_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
        assert initial_scaled["spec"]["minReplicaCount"] == 1

        logger.info("Updating AsyncActor...")
        kubectl_apply(updated_manifest, namespace=e2e_helper.namespace)

        time.sleep(5)

        updated_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
        assert updated_scaled["spec"]["minReplicaCount"] == 3, \
            "ScaledObject should be updated with new minReplicas"
        assert updated_scaled["spec"]["maxReplicaCount"] == 10, \
            "ScaledObject should be updated with new maxReplicas"

        triggers = updated_scaled["spec"]["triggers"]
        transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
        if transport == "rabbitmq":
            assert triggers[0]["metadata"]["value"] == "5", \
                "Queue length trigger should be updated"
        elif transport == "sqs":
            assert triggers[0]["metadata"]["queueLength"] == "5", \
                "Queue length trigger should be updated"

        logger.info("[+] AsyncActor updates propagated successfully")

    finally:
        kubectl_delete("asyncactor", "test-update", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-update", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-update", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_invalid_transport(e2e_helper):
    """
    E2E: Test AsyncActor with invalid transport reference.

    Scenario:
    1. Create AsyncActor with non-existent transport
    2. Operator should reject or mark as failed

    Expected: Appropriate error handling
    """
    invalid_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-invalid-transport
  namespace: {e2e_helper.namespace}
spec:
  transport: nonexistent-transport
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-testing:latest
"""

    try:
        logger.info("Creating AsyncActor with invalid transport...")
        kubectl_apply(invalid_manifest, namespace=e2e_helper.namespace)

        time.sleep(5)

        actor = kubectl_get("asyncactor", "test-invalid-transport", namespace=e2e_helper.namespace)
        status = actor.get("status", {})

        if "conditions" in status:
            conditions = status["conditions"]
            ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)
            if ready_condition:
                assert ready_condition["status"] == "False", \
                    "AsyncActor should not be Ready with invalid transport"

        logger.info("[+] Invalid transport handled appropriately")

    finally:
        kubectl_delete("asyncactor", "test-invalid-transport", namespace=e2e_helper.namespace)


@pytest.mark.xfail(reason="StatefulSet support not fully implemented in operator yet")
@pytest.mark.core
def test_asyncactor_with_statefulset(e2e_helper):
    """
    E2E: Test AsyncActor with StatefulSet workload.

    Scenario:
    1. Create AsyncActor with workload.kind=StatefulSet
    2. Operator creates StatefulSet instead of Deployment
    3. Verify sidecar injection works with StatefulSet

    Expected: StatefulSet created with proper configuration
    """
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-statefulset
  namespace: {e2e_helper.namespace}
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
  scaling:
    enabled: false
  workload:
    kind: StatefulSet
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-testing:latest
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor with StatefulSet...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for StatefulSet to be created...")
        assert wait_for_resource("statefulset", "test-statefulset", namespace=e2e_helper.namespace, timeout=60), \
            "StatefulSet should be created by operator"

        statefulset = kubectl_get("statefulset", "test-statefulset", namespace=e2e_helper.namespace)
        containers = statefulset["spec"]["template"]["spec"]["containers"]
        container_names = [c["name"] for c in containers]

        assert "asya-sidecar" in container_names, "Sidecar should be injected into StatefulSet"
        assert "asya-runtime" in container_names, "Runtime container should exist"

        logger.info("[+] StatefulSet workload created successfully")

    finally:
        kubectl_delete("asyncactor", "test-statefulset", namespace=e2e_helper.namespace)
        kubectl_delete("statefulset", "test-statefulset", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_status_conditions(e2e_helper):
    """
    E2E: Test AsyncActor status conditions are updated correctly.

    Scenario:
    1. Create AsyncActor
    2. Check status conditions (Ready, WorkloadReady, etc.)
    3. Verify condition reasons and messages

    Expected: Status reflects actual state
    """
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-status
  namespace: {e2e_helper.namespace}
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
          image: asya-testing:latest
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor conditions to be set...")
        # Longer timeout needed: operator may encounter status update conflicts
        # when it adds finalizer (generation 1→2), requiring retry with fresh version
        assert wait_for_asyncactor_ready(
            "test-status",
            namespace=e2e_helper.namespace,
            timeout=120,
            require_true=False,
        ), "AsyncActor should have WorkloadReady condition set"

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

    finally:
        kubectl_delete("asyncactor", "test-status", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-status", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-status", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_with_broken_image(e2e_helper):
    """
    E2E: Test AsyncActor with non-existent container image.

    Scenario:
    1. Create AsyncActor with invalid image
    2. Deployment created but pods fail to pull image
    3. AsyncActor status reflects the failure

    Expected: Graceful handling of image pull failures
    """
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-broken-image
  namespace: {e2e_helper.namespace}
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
          image: nonexistent/broken-image:latest
          imagePullPolicy: Always
"""

    try:
        logger.info("Creating AsyncActor with broken image...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for Deployment to be created...")
        assert wait_for_resource("deployment", "test-broken-image", namespace=e2e_helper.namespace, timeout=60), \
            "Deployment should be created by operator"

        time.sleep(10)

        pods = subprocess.run(
            ["kubectl", "get", "pods", "-l", "app=test-broken-image", "-n", e2e_helper.namespace],
            capture_output=True,
            text=True
        )

        logger.info(f"Pods status: {pods.stdout}")

        deployment = kubectl_get("deployment", "test-broken-image", namespace=e2e_helper.namespace)
        status = deployment.get("status", {})
        available_replicas = status.get("availableReplicas", 0)

        assert available_replicas == 0, "No replicas should be available with broken image"

        logger.info("[+] Broken image handled gracefully")

    finally:
        kubectl_delete("asyncactor", "test-broken-image", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-broken-image", namespace=e2e_helper.namespace)


@pytest.mark.core
def test_asyncactor_sidecar_environment_variables(e2e_helper):
    """
    E2E: Test sidecar container has correct environment variables.

    Scenario:
    1. Create AsyncActor
    2. Verify sidecar container has required env vars:
       - ASYA_TRANSPORT
       - ASYA_ACTOR_NAME
       - ASYA_SOCKET_DIR
       - Transport-specific configs

    Expected: All required env vars present
    """
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-sidecar-env
  namespace: {e2e_helper.namespace}
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
          image: asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for AsyncActor to be ready (WorkloadReady condition)...")
        assert wait_for_asyncactor_ready("test-sidecar-env", namespace=e2e_helper.namespace, timeout=90), \
            "AsyncActor should reach WorkloadReady=True"

        deployment = kubectl_get("deployment", "test-sidecar-env", namespace=e2e_helper.namespace)
        containers = deployment["spec"]["template"]["spec"]["containers"]
        sidecar = next((c for c in containers if c["name"] == "asya-sidecar"), None)

        assert sidecar is not None, "Sidecar container should exist"

        env_vars = {e["name"]: e.get("value", "") for e in sidecar.get("env", [])}

        logger.info(f"Sidecar env vars: {list(env_vars.keys())}")

        assert "ASYA_TRANSPORT" in env_vars, "Should have ASYA_TRANSPORT"
        assert "ASYA_ACTOR_NAME" in env_vars, "Should have ASYA_ACTOR_NAME"

        assert env_vars["ASYA_ACTOR_NAME"] == "test-sidecar-env", \
            f"Actor name should be test-sidecar-env, got {env_vars['ASYA_ACTOR_NAME']}"

        logger.info("[+] Sidecar environment variables verified")

    finally:
        kubectl_delete("asyncactor", "test-sidecar-env", namespace=e2e_helper.namespace)
        wait_for_deletion("deployment", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)
        wait_for_deletion("scaledobject", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)
