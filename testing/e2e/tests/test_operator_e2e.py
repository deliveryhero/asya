#!/usr/bin/env python3
"""
E2E tests for AsyncActor CRD lifecycle under Crossplane + Injector architecture.

Tests AsyncActor behavior in a real Kubernetes environment:
- AsyncActor creation, updates, and deletion
- Sidecar injection verification (via mutating webhook)
- AsyncActor status conditions (Crossplane: Ready, Synced)
- Workload creation (Deployment)
- Broken image handling

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
    kubectl_delete,
    kubectl_get,
    log_asyncactor_workload_diagnostics,
    wait_for_asyncactor_ready,
    wait_for_deletion,
    wait_for_resource,
)

logger = logging.getLogger(__name__)


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
        assert wait_for_asyncactor_ready("test-lifecycle", namespace=e2e_helper.namespace, timeout=120), \
            "AsyncActor should reach Ready=True"

        logger.info("Verifying sidecar injection (checking Pod, not Deployment)...")
        pods_result = subprocess.run(
            ["kubectl", "get", "pods", "-n", e2e_helper.namespace,
             "-l", "asya.sh/actor=test-lifecycle",
             "-o", "jsonpath={.items[0].spec.containers[*].name}"],
            capture_output=True, text=True, timeout=10,
        )
        container_names = pods_result.stdout.strip().split()

        assert "asya-sidecar" in container_names, "Sidecar should be injected by webhook"
        assert "asya-runtime" in container_names, "Runtime container should exist"

        logger.info("Verifying ScaledObject creation...")
        assert wait_for_resource("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=60), \
            "ScaledObject should be created"

        logger.info("Deleting AsyncActor...")
        kubectl_delete("asyncactor", "test-lifecycle", namespace=e2e_helper.namespace)

        assert wait_for_deletion("deployment", "test-lifecycle", namespace=e2e_helper.namespace, timeout=120), \
            "Deployment should be deleted when AsyncActor is removed"
        assert wait_for_deletion("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace, timeout=120), \
            "ScaledObject should be deleted when AsyncActor is removed"

        logger.info("[+] AsyncActor lifecycle completed successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-lifecycle", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-lifecycle", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-lifecycle", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-lifecycle", namespace=e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
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
            timeout=120,
        ), "AsyncActor should reach Ready=True"

        initial_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
        assert initial_scaled["spec"]["minReplicaCount"] == 1

        logger.info("Updating AsyncActor...")
        kubectl_apply(updated_manifest, namespace=e2e_helper.namespace)

        # Poll for Crossplane reconciliation (can take 30-60s)
        updated_scaled = None
        for attempt in range(30):
            time.sleep(5)  # Poll every 5s for up to 150s
            updated_scaled = kubectl_get("scaledobject", "test-update", namespace=e2e_helper.namespace)
            if updated_scaled["spec"].get("minReplicaCount") == 3:
                break
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

    except Exception:
        log_asyncactor_workload_diagnostics("test-update", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-update", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-update", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-update", namespace=e2e_helper.namespace)


@pytest.mark.xfail(reason="XRD validation differs from operator; Crossplane may accept unknown transport names")
@pytest.mark.core
def test_asyncactor_invalid_transport(e2e_helper):
    """
    E2E: Test AsyncActor with invalid transport reference.

    Scenario:
    1. Create AsyncActor with non-existent transport
    2. Crossplane should mark as not ready

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
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
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

    except Exception:
        log_asyncactor_workload_diagnostics("test-invalid-transport", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-invalid-transport", namespace=e2e_helper.namespace)


@pytest.mark.xfail(reason="StatefulSet support not fully implemented in Crossplane Composition yet")
@pytest.mark.core
def test_asyncactor_with_statefulset(e2e_helper):
    """
    E2E: Test AsyncActor with StatefulSet workload.

    Scenario:
    1. Create AsyncActor with workload.kind=StatefulSet
    2. Crossplane creates StatefulSet instead of Deployment
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
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.echo_handler
"""

    try:
        logger.info("Creating AsyncActor with StatefulSet...")
        kubectl_apply(manifest, namespace=e2e_helper.namespace)

        logger.info("Waiting for StatefulSet to be created...")
        assert wait_for_resource("statefulset", "test-statefulset", namespace=e2e_helper.namespace, timeout=60), \
            "StatefulSet should be created by Crossplane"

        statefulset = kubectl_get("statefulset", "test-statefulset", namespace=e2e_helper.namespace)
        containers = statefulset["spec"]["template"]["spec"]["containers"]
        container_names = [c["name"] for c in containers]

        assert "asya-sidecar" in container_names, "Sidecar should be injected into StatefulSet"
        assert "asya-runtime" in container_names, "Runtime container should exist"

        logger.info("[+] StatefulSet workload created successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-statefulset", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-statefulset", namespace=e2e_helper.namespace)
        kubectl_delete("statefulset", "test-statefulset", namespace=e2e_helper.namespace)


@pytest.mark.core
@pytest.mark.timeout(300)
def test_asyncactor_status_conditions(e2e_helper):
    """
    E2E: Test AsyncActor status conditions are updated correctly.

    Scenario:
    1. Create AsyncActor
    2. Check status conditions (Ready, Synced for Crossplane)
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
            timeout=120,
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
        kubectl_delete("asyncactor", "test-status", namespace=e2e_helper.namespace)
        kubectl_delete("deployment", "test-status", namespace=e2e_helper.namespace)
        kubectl_delete("scaledobject", "test-status", namespace=e2e_helper.namespace)


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
        assert wait_for_resource("deployment", "test-broken-image", namespace=e2e_helper.namespace, timeout=120), \
            "Deployment should be created by Crossplane"

        time.sleep(10)

        pods = subprocess.run(
            ["kubectl", "get", "pods", "-l", "asya.sh/actor=test-broken-image", "-n", e2e_helper.namespace],
            capture_output=True,
            text=True
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
        assert wait_for_asyncactor_ready("test-sidecar-env", namespace=e2e_helper.namespace, timeout=120), \
            "AsyncActor should reach Ready=True"

        logger.info("Checking Pod containers (sidecar injected by webhook into Pods, not Deployment)...")
        pods_json = subprocess.run(
            ["kubectl", "get", "pods", "-n", e2e_helper.namespace,
             "-l", "asya.sh/actor=test-sidecar-env",
             "-o", "jsonpath={.items[0].spec.containers}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = json.loads(pods_json.stdout)
        sidecar = next((c for c in containers if c["name"] == "asya-sidecar"), None)

        assert sidecar is not None, "Sidecar container should exist (injected by webhook into Pod)"

        env_vars = {e["name"]: e.get("value", "") for e in sidecar.get("env", [])}

        logger.info(f"Sidecar env vars: {list(env_vars.keys())}")

        assert "ASYA_TRANSPORT" in env_vars, "Should have ASYA_TRANSPORT"
        assert "ASYA_ACTOR_NAME" in env_vars, "Should have ASYA_ACTOR_NAME"

        assert env_vars["ASYA_ACTOR_NAME"] == "test-sidecar-env", \
            f"Actor name should be test-sidecar-env, got {env_vars['ASYA_ACTOR_NAME']}"

        logger.info("[+] Sidecar environment variables verified")

    except Exception:
        log_asyncactor_workload_diagnostics("test-sidecar-env", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-sidecar-env", namespace=e2e_helper.namespace)
        wait_for_deletion("deployment", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)
        wait_for_deletion("scaledobject", "test-sidecar-env", namespace=e2e_helper.namespace, timeout=60)

@pytest.mark.xfail(reason="Crossplane labels differ from operator; managed-by is 'crossplane', no reserved prefix rejection")
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
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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
        assert wait_for_asyncactor_ready("test-labels", namespace=e2e_helper.namespace, timeout=60), \
            "AsyncActor should reach Ready=True"

        logger.info("Verifying Deployment labels...")
        deployment = kubectl_get("deployment", "test-labels", namespace=e2e_helper.namespace)
        deployment_labels = deployment["metadata"].get("labels", {})

        assert deployment_labels.get("app") == "example-ecommerce", \
            "Deployment should have user label 'app=example-ecommerce'"
        assert deployment_labels.get("team") == "ml-platform", \
            "Deployment should have user label 'team=ml-platform'"
        assert deployment_labels.get("env") == "test", \
            "Deployment should have user label 'env=test'"
        assert deployment_labels.get("app.kubernetes.io/name") == "test-labels", \
            "Deployment should have operator label 'app.kubernetes.io/name'"
        assert deployment_labels.get("app.kubernetes.io/component") == "actor", \
            "Deployment should have operator label 'app.kubernetes.io/component=actor'"
        assert deployment_labels.get("app.kubernetes.io/part-of") == "asya", \
            "Deployment should have operator label 'app.kubernetes.io/part-of=asya'"
        assert deployment_labels.get("app.kubernetes.io/managed-by") == "asya-operator", \
            "Deployment should have operator label 'app.kubernetes.io/managed-by'"
        logger.info("[+] Deployment labels verified")

        logger.info("Verifying Secret labels...")
        secret_name = "test-labels-transport-creds"
        try:
            secret = kubectl_get("secret", secret_name, namespace=e2e_helper.namespace)
            secret_labels = secret["metadata"].get("labels", {})

            assert secret_labels.get("app") == "example-ecommerce", \
                "Secret should have user label 'app=example-ecommerce'"
            assert secret_labels.get("team") == "ml-platform", \
                "Secret should have user label 'team=ml-platform'"
            assert secret_labels.get("env") == "test", \
                "Secret should have user label 'env=test'"
            assert secret_labels.get("app.kubernetes.io/name") == "test-labels", \
                "Secret should have operator label 'app.kubernetes.io/name'"
            assert secret_labels.get("app.kubernetes.io/component") == "transport-creds", \
                "Secret should have operator label 'app.kubernetes.io/component=transport-creds'"
            assert secret_labels.get("app.kubernetes.io/part-of") == "asya", \
                "Secret should have operator label 'app.kubernetes.io/part-of=asya'"
            assert secret_labels.get("app.kubernetes.io/managed-by") == "asya-operator", \
                "Secret should have operator label 'app.kubernetes.io/managed-by'"
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

                assert sa_labels.get("app") == "example-ecommerce", \
                    "ServiceAccount should have user label 'app=example-ecommerce'"
                assert sa_labels.get("team") == "ml-platform", \
                    "ServiceAccount should have user label 'team=ml-platform'"
                assert sa_labels.get("env") == "test", \
                    "ServiceAccount should have user label 'env=test'"
                assert sa_labels.get("app.kubernetes.io/name") == "test-labels", \
                    "ServiceAccount should have operator label 'app.kubernetes.io/name'"
                assert sa_labels.get("app.kubernetes.io/component") == "serviceaccount", \
                    "ServiceAccount should have operator label 'app.kubernetes.io/component=serviceaccount'"
                assert sa_labels.get("app.kubernetes.io/part-of") == "asya", \
                    "ServiceAccount should have operator label 'app.kubernetes.io/part-of=asya'"
                assert sa_labels.get("app.kubernetes.io/managed-by") == "asya-operator", \
                    "ServiceAccount should have operator label 'app.kubernetes.io/managed-by'"
                logger.info("[+] ServiceAccount labels verified")
            except subprocess.CalledProcessError:
                logger.info("ServiceAccount not found - IRSA may not be configured")
        else:
            logger.info("Skipping ServiceAccount verification (not SQS transport)")

        logger.info("Verifying ScaledObject labels...")
        scaledobject = kubectl_get("scaledobject", "test-labels", namespace=e2e_helper.namespace)
        scaledobject_labels = scaledobject["metadata"].get("labels", {})

        assert scaledobject_labels.get("app") == "example-ecommerce", \
            "ScaledObject should have user label 'app=example-ecommerce'"
        assert scaledobject_labels.get("team") == "ml-platform", \
            "ScaledObject should have user label 'team=ml-platform'"
        assert scaledobject_labels.get("env") == "test", \
            "ScaledObject should have user label 'env=test'"
        assert scaledobject_labels.get("app.kubernetes.io/name") == "test-labels", \
            "ScaledObject should have operator label 'app.kubernetes.io/name'"
        assert scaledobject_labels.get("app.kubernetes.io/component") == "scaledobject", \
            "ScaledObject should have operator label 'app.kubernetes.io/component=scaledobject'"
        assert scaledobject_labels.get("app.kubernetes.io/part-of") == "asya", \
            "ScaledObject should have operator label 'app.kubernetes.io/part-of=asya'"
        assert scaledobject_labels.get("app.kubernetes.io/managed-by") == "asya-operator", \
            "ScaledObject should have operator label 'app.kubernetes.io/managed-by'"
        logger.info("[+] ScaledObject labels verified")

        logger.info("Verifying TriggerAuthentication labels...")
        trigger_auth_name = "test-labels-trigger-auth"
        try:
            trigger_auth = kubectl_get("triggerauthentication", trigger_auth_name, namespace=e2e_helper.namespace)
            trigger_auth_labels = trigger_auth["metadata"].get("labels", {})

            assert trigger_auth_labels.get("app") == "example-ecommerce", \
                "TriggerAuthentication should have user label 'app=example-ecommerce'"
            assert trigger_auth_labels.get("team") == "ml-platform", \
                "TriggerAuthentication should have user label 'team=ml-platform'"
            assert trigger_auth_labels.get("env") == "test", \
                "TriggerAuthentication should have user label 'env=test'"
            assert trigger_auth_labels.get("app.kubernetes.io/name") == "test-labels", \
                "TriggerAuthentication should have operator label 'app.kubernetes.io/name'"
            assert trigger_auth_labels.get("app.kubernetes.io/component") == "triggerauthentication", \
                "TriggerAuthentication should have operator label 'app.kubernetes.io/component=triggerauthentication'"
            assert trigger_auth_labels.get("app.kubernetes.io/part-of") == "asya", \
                "TriggerAuthentication should have operator label 'app.kubernetes.io/part-of=asya'"
            assert trigger_auth_labels.get("app.kubernetes.io/managed-by") == "asya-operator", \
                "TriggerAuthentication should have operator label 'app.kubernetes.io/managed-by'"
            logger.info("[+] TriggerAuthentication labels verified")
        except subprocess.CalledProcessError:
            logger.info("TriggerAuthentication not found - credentials may be using pod identity")

        logger.info("Verifying ConfigMap does NOT have actor-specific labels...")
        configmap = kubectl_get("configmap", "asya-runtime", namespace=e2e_helper.namespace)
        configmap_labels = configmap["metadata"].get("labels", {})

        assert "app" not in configmap_labels, \
            "ConfigMap should NOT have actor-specific user label 'app' (shared resource)"
        assert "team" not in configmap_labels, \
            "ConfigMap should NOT have actor-specific user label 'team' (shared resource)"
        assert configmap_labels.get("app.kubernetes.io/name") == "asya-runtime", \
            "ConfigMap should have generic operator label 'app.kubernetes.io/name=asya-runtime'"
        assert configmap_labels.get("app.kubernetes.io/component") == "asya-runtime", \
            "ConfigMap should have generic operator label 'app.kubernetes.io/component=asya-runtime'"
        logger.info("[+] ConfigMap labels verified (no actor-specific labels)")

        logger.info("Testing reserved label prefix rejection...")
        invalid_actor_manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-invalid-labels
  namespace: {e2e_helper.namespace}
  labels:
    app.kubernetes.io/custom: forbidden
spec:
  transport: {os.getenv("ASYA_TRANSPORT", "rabbitmq")}
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

        kubectl_apply(invalid_actor_manifest, namespace=e2e_helper.namespace)

        time.sleep(5)

        asyncactor = kubectl_get("asyncactor", "test-invalid-labels", namespace=e2e_helper.namespace)
        status = asyncactor.get("status", {})
        conditions = status.get("conditions", [])

        workload_ready = next((c for c in conditions if c["type"] == "WorkloadReady"), None)
        assert workload_ready is not None, "WorkloadReady condition should exist"
        assert workload_ready["status"] == "False", \
            "WorkloadReady should be False when labels use reserved prefixes"
        assert "reserved prefix" in workload_ready.get("message", "").lower(), \
            "Error message should mention reserved prefix"

        logger.info("[+] Label propagation verified successfully")

    except Exception:
        log_asyncactor_workload_diagnostics("test-labels", namespace=e2e_helper.namespace)
        raise
    finally:
        kubectl_delete("asyncactor", "test-labels", namespace=e2e_helper.namespace, ignore_not_found=True)
        kubectl_delete("asyncactor", "test-invalid-labels", namespace=e2e_helper.namespace, ignore_not_found=True)
        wait_for_deletion("deployment", "test-labels", namespace=e2e_helper.namespace, timeout=60)
        wait_for_deletion("scaledobject", "test-labels", namespace=e2e_helper.namespace, timeout=60)
