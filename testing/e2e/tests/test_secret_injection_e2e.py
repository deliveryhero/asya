#!/usr/bin/env python3
"""
E2E tests for AsyncActor secretRefs — Kubernetes Secret injection.

Verifies that when spec.secretRefs is set on an AsyncActor, the injector
webhook populates env[].valueFrom.secretKeyRef on the runtime container,
and the running actor process can read the injected env var values.

Test flow:
1. Create a K8s Secret with a known token value
2. Create an AsyncActor with spec.secretRefs pointing to that Secret
3. Wait for the AsyncActor to be Ready (pod running proves K8s resolved the Secret)
4. Verify pod spec has secretKeyRef env on the runtime container (injection check)
5. kubectl exec into the runtime container, read the env var (runtime read check)
6. Clean up Secret and AsyncActor
"""

import json
import logging
import os
import subprocess

import pytest

from asya_testing.utils.kubectl import (
    kubectl_apply,
    kubectl_delete,
    log_asyncactor_workload_diagnostics,
    wait_for_asyncactor_ready,
)


logger = logging.getLogger(__name__)

TRANSPORT = os.getenv("ASYA_TRANSPORT", "rabbitmq")
GCP_PROJECT = os.getenv("ASYA_PUBSUB_PROJECT_ID", "")

# Known test value written into the K8s Secret
_TEST_SECRET_VALUE = "e2e-test-token-abc123"


def _cleanup_actor(name: str, namespace: str) -> None:
    """Best-effort cleanup of an AsyncActor and its child resources."""
    kubectl_delete("asyncactor", name, namespace=namespace)
    kubectl_delete("deployment", name, namespace=namespace)
    kubectl_delete("scaledobject", name, namespace=namespace)


def _get_runtime_env(actor_name: str, namespace: str) -> list[dict]:
    """Return the env list from the asya-runtime container of the actor's first Pod."""
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
            "jsonpath={.items[0].spec.containers[?(@.name=='asya-runtime')].env}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    raw = result.stdout.strip()
    if not raw:
        return []
    return json.loads(raw)


def _exec_printenv(actor_name: str, namespace: str, var_name: str) -> str:
    """
    kubectl exec into the running asya-runtime container and return the value
    of env var var_name (empty string if the pod is not running or var is unset).
    """
    pod_result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"asya.sh/actor={actor_name}",
            "--field-selector=status.phase=Running",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    pod_name = pod_result.stdout.strip()
    if not pod_name:
        return ""

    exec_result = subprocess.run(
        [
            "kubectl",
            "exec",
            "-n",
            namespace,
            pod_name,
            "-c",
            "asya-runtime",
            "--",
            "printenv",
            var_name,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return exec_result.stdout.strip()


@pytest.mark.core
@pytest.mark.timeout(300)
def test_secretrefs_injection(e2e_helper):
    """
    E2E: AsyncActor with spec.secretRefs injects K8s Secret keys as env vars
    into the runtime container, and the running actor process can read them.

    Scenario:
    1. Create a K8s Secret containing a known token value
    2. Create an AsyncActor with spec.secretRefs referencing that Secret
    3. Crossplane creates Deployment; injector webhook injects secretKeyRef env
    4. K8s resolves the Secret and starts the Pod
    5. Verify runtime container pod spec has secretKeyRef pointing to our Secret
    6. kubectl exec to read the env var value from the running container

    Expected:
    - Pod reaches Running state (proves K8s resolved the Secret)
    - Runtime container env has TEST_API_KEY with secretKeyRef.name == secret name
    - printenv TEST_API_KEY in the container returns the known token value
    """
    actor_name = "test-secretrefs"
    secret_name = "test-actor-creds"
    namespace = e2e_helper.namespace

    gcp_project_line = f"\n  gcpProject: {GCP_PROJECT}" if TRANSPORT == "pubsub" and GCP_PROJECT else ""

    secret_manifest = f"""\
apiVersion: v1
kind: Secret
metadata:
  name: {secret_name}
  namespace: {namespace}
stringData:
  api_key: {_TEST_SECRET_VALUE}
"""

    actor_manifest = f"""\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  transport: {TRANSPORT}{gcp_project_line}
  scaling:
    enabled: false
  workload:
    kind: Deployment
    replicas: 1
    template:
      spec:
        containers:
        - name: asya-runtime
          image: ghcr.io/deliveryhero/asya-testing:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: asya_testing.handlers.payload.secret_echo_handler
  secretRefs:
    - secretName: {secret_name}
      keys:
        - key: api_key
          envVar: TEST_API_KEY
"""

    try:
        logger.info("Creating K8s Secret %s in namespace %s", secret_name, namespace)
        kubectl_apply(secret_manifest, namespace=namespace)

        logger.info("Creating AsyncActor %s with secretRefs", actor_name)
        kubectl_apply(actor_manifest, namespace=namespace)

        logger.info("Waiting for AsyncActor %s to be Ready...", actor_name)
        assert wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=180), (
            f"AsyncActor {actor_name} should reach Ready=True within timeout"
        )

        # --- Injection check: pod spec has secretKeyRef env ---
        logger.info("Verifying secretKeyRef env on runtime container pod spec...")
        env_list = _get_runtime_env(actor_name, namespace)
        secret_envs = {
            e["name"]: e["valueFrom"]["secretKeyRef"]
            for e in env_list
            if "valueFrom" in e and "secretKeyRef" in e.get("valueFrom", {})
        }

        assert "TEST_API_KEY" in secret_envs, (
            f"TEST_API_KEY not found in runtime container env; secret envs present: {list(secret_envs)}"
        )
        sel = secret_envs["TEST_API_KEY"]
        assert sel["name"] == secret_name, (
            f"secretKeyRef.name expected {secret_name!r}, got {sel['name']!r}"
        )
        assert sel["key"] == "api_key", (
            f"secretKeyRef.key expected 'api_key', got {sel['key']!r}"
        )
        logger.info("[+] secretKeyRef injection verified on pod spec")

        # --- Runtime read check: env var has the secret value in the running container ---
        logger.info("Exec-ing into runtime container to verify env var value...")
        actual_value = _exec_printenv(actor_name, namespace, "TEST_API_KEY")
        assert actual_value == _TEST_SECRET_VALUE, (
            f"TEST_API_KEY value in container expected {_TEST_SECRET_VALUE!r}, got {actual_value!r}"
        )
        logger.info("[+] K8s Secret value read successfully from running container: %r", actual_value)

    except Exception:
        log_asyncactor_workload_diagnostics(actor_name, namespace=namespace)
        raise
    finally:
        _cleanup_actor(actor_name, namespace)
        kubectl_delete("secret", secret_name, namespace=namespace)
