"""
Kubectl utilities for E2E tests.

Provides helpers for common kubectl operations:
- Apply/delete/get resources
- Wait for resources to be ready
- Query resource status

These utilities reduce code duplication across E2E test files.
"""

import logging
import subprocess
import time

import yaml  # type: ignore[import-untyped]


logger = logging.getLogger(__name__)


def kubectl_apply(manifest_yaml: str, namespace: str = "asya-e2e") -> None:
    """
    Apply a Kubernetes manifest using kubectl.

    Args:
        manifest_yaml: YAML manifest as string
        namespace: Target namespace

    Raises:
        CalledProcessError: If kubectl command fails
    """
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-", "-n", namespace],
        input=manifest_yaml.encode(),
        capture_output=True,
        check=True,
        timeout=30,
    )
    logger.debug(f"kubectl apply output: {result.stdout.decode()}")


def kubectl_delete(
    resource_type: str,
    name: str,
    namespace: str = "asya-e2e",
    ignore_not_found: bool = True,
    wait: bool = False,
    timeout: int = 60,
) -> None:
    """
    Delete a Kubernetes resource using kubectl.

    Args:
        resource_type: Resource type (e.g., "pod", "deployment")
        name: Resource name
        namespace: Target namespace
        ignore_not_found: Don't fail if resource doesn't exist
        wait: Wait for deletion to complete
        timeout: Maximum wait time in seconds
    """
    cmd = ["kubectl", "delete", resource_type, name, "-n", namespace]
    if ignore_not_found:
        cmd.append("--ignore-not-found=true")
    if wait:
        cmd.append(f"--timeout={timeout}s")

    subprocess.run(cmd, capture_output=True, check=not ignore_not_found, timeout=timeout + 10)


def kubectl_get(resource_type: str, name: str, namespace: str = "asya-e2e", output: str = "json") -> dict:
    """
    Get a Kubernetes resource using kubectl.

    Args:
        resource_type: Resource type (e.g., "pod", "deployment")
        name: Resource name
        namespace: Target namespace
        output: Output format (json or yaml)

    Returns:
        Parsed resource object as dict

    Raises:
        CalledProcessError: If resource not found or kubectl fails
    """
    result = subprocess.run(
        ["kubectl", "get", resource_type, name, "-n", namespace, f"-o={output}"],
        capture_output=True,
        check=True,
        timeout=10,
    )
    return yaml.safe_load(result.stdout.decode())


def wait_for_resource(resource_type: str, name: str, namespace: str = "asya-e2e", timeout: int = 60) -> bool:
    """
    Wait for a Kubernetes resource to exist.

    Args:
        resource_type: Resource type (e.g., "pod", "deployment")
        name: Resource name
        namespace: Target namespace
        timeout: Maximum wait time in seconds

    Returns:
        True if resource exists, False if timeout
    """
    start = time.time()
    attempt = 0

    while time.time() - start < timeout:
        attempt += 1
        try:
            result = subprocess.run(
                ["kubectl", "get", resource_type, name, "-n", namespace], capture_output=True, timeout=5
            )
            if result.returncode == 0:
                elapsed = time.time() - start
                logger.info(f"{resource_type}/{name} found after {elapsed:.1f}s ({attempt} attempts)")
                return True
        except Exception as e:
            logger.debug(f"Error checking resource (attempt {attempt}): {e}")

        sleep_time = min(2 ** (attempt // 2), 5)
        time.sleep(sleep_time)

    logger.warning(f"{resource_type}/{name} not found after {timeout}s ({attempt} attempts)")
    return False


def wait_for_deletion(resource_type: str, name: str, namespace: str = "asya-e2e", timeout: int = 60) -> bool:
    """
    Wait for a Kubernetes resource to be deleted (finalizers completed).

    Args:
        resource_type: Resource type (e.g., "pod", "deployment")
        name: Resource name
        namespace: Target namespace
        timeout: Maximum wait time in seconds

    Returns:
        True if resource is deleted, False if timeout
    """
    start = time.time()
    attempt = 0

    while time.time() - start < timeout:
        attempt += 1
        try:
            result = subprocess.run(
                ["kubectl", "get", resource_type, name, "-n", namespace], capture_output=True, timeout=5
            )
            if result.returncode != 0:
                elapsed = time.time() - start
                logger.info(f"{resource_type}/{name} deleted after {elapsed:.1f}s ({attempt} attempts)")
                return True
        except Exception as e:
            logger.debug(f"Error checking deletion (attempt {attempt}): {e}")

        sleep_time = min(2 ** (attempt // 2), 5)
        time.sleep(sleep_time)

    logger.warning(f"{resource_type}/{name} not deleted after {timeout}s ({attempt} attempts)")
    return False


def wait_for_deployment_ready(name: str, namespace: str = "asya-e2e", timeout: int = 60) -> bool:
    """
    Wait for a deployment to be ready (available condition).

    Args:
        name: Deployment name
        namespace: Target namespace
        timeout: Maximum wait time in seconds

    Returns:
        True if deployment becomes ready, False if timeout
    """
    result = subprocess.run(
        [
            "kubectl",
            "wait",
            "--for=condition=available",
            f"--timeout={timeout}s",
            f"deployment/{name}",
            "-n",
            namespace,
        ],
        capture_output=True,
        timeout=timeout + 5,
    )
    return result.returncode == 0


def wait_for_pod_ready(
    label_selector: str, namespace: str = "asya-e2e", timeout: int = 60, poll_interval: float = 1.0
) -> bool:
    """
    Wait for at least one pod matching label selector to be ready.

    Args:
        label_selector: Kubernetes label selector (e.g., "app=my-app")
        namespace: Target namespace
        timeout: Maximum wait time in seconds
        poll_interval: Polling interval in seconds

    Returns:
        True if pod is ready, False if timeout
    """
    start_time = time.time()
    attempt = 0

    while time.time() - start_time < timeout:
        attempt += 1
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    namespace,
                    "-l",
                    label_selector,
                    "-o",
                    "jsonpath='{.items[?(@.status.phase==\"Running\")].status.containerStatuses[?(@.ready==true)].name}'",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            output = result.stdout.strip()
            if output and output != "''":
                elapsed = time.time() - start_time
                logger.info(f"Pod with label {label_selector} ready after {elapsed:.2f}s ({attempt} attempts)")
                return True

        except Exception as e:
            logger.debug(f"Error checking pod status (attempt {attempt}): {e}")

        time.sleep(poll_interval)

    logger.warning(f"Pod with label {label_selector} not ready after {timeout}s ({attempt} attempts)")
    return False


def get_pod_count(label_selector: str, namespace: str = "asya-e2e") -> int:
    """
    Get number of running pods matching label selector.

    Args:
        label_selector: Kubernetes label selector
        namespace: Target namespace

    Returns:
        Number of matching pods
    """
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", namespace, "-l", label_selector, "-o", "jsonpath='{.items[*].metadata.name}'"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    if result.returncode != 0:
        return 0

    output = result.stdout.strip()
    if not output or output == "''":
        return 0

    pod_names = output.strip("'").split()
    return len(pod_names)


def delete_pod(pod_name: str, namespace: str = "asya-e2e", force: bool = True) -> None:
    """
    Delete a pod (useful for simulating crashes).

    Args:
        pod_name: Pod name
        namespace: Target namespace
        force: Use --force flag for immediate deletion
    """
    cmd = ["kubectl", "delete", "pod", pod_name, "-n", namespace]

    if force:
        cmd.extend(["--grace-period=0", "--force"])

    subprocess.run(cmd, capture_output=True, check=False, timeout=30)


def wait_for_operator_log(
    actor_name: str,
    log_pattern: str,
    namespace: str = "asya-e2e",
    operator_namespace: str = "asya-system",
    timeout: int = 30,
    resource_type: str | None = None,
    resource_name: str | None = None,
) -> bool:
    """
    Wait for operator log message and optionally verify resource exists.

    Args:
        actor_name: AsyncActor name to watch for
        log_pattern: Log pattern to match (e.g., "Deployment reconciled")
        namespace: AsyncActor namespace
        operator_namespace: Operator deployment namespace
        timeout: Maximum wait time in seconds
        resource_type: Optional resource type to verify exists (e.g., "deployment")
        resource_name: Optional resource name to verify exists

    Returns:
        True if log found and resource exists (if specified), False if timeout
    """
    start_time = time.time()
    attempt = 0
    log_found = False

    while time.time() - start_time < timeout:
        attempt += 1

        if not log_found:
            try:
                since_seconds = int(time.time() - start_time) + 5
                log_result = subprocess.run(
                    [
                        "kubectl",
                        "logs",
                        "-n",
                        operator_namespace,
                        "-l",
                        "control-plane=controller-manager",
                        "--tail=100",
                        f"--since={since_seconds}s",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if log_result.returncode == 0:
                    logs = log_result.stdout
                    if actor_name in logs and log_pattern in logs:
                        elapsed_time = time.time() - start_time
                        logger.info(
                            f"Operator log '{log_pattern}' for {actor_name} found after {elapsed_time:.1f}s ({attempt} attempts)"
                        )
                        log_found = True

                        if not resource_type or not resource_name:
                            return True

            except Exception as e:
                logger.debug(f"Error checking operator logs (attempt {attempt}): {e}")

        if log_found and resource_type and resource_name:
            try:
                get_result = subprocess.run(
                    ["kubectl", "get", resource_type, resource_name, "-n", namespace],
                    capture_output=True,
                    timeout=5,
                )
                if get_result.returncode == 0:
                    elapsed_time = time.time() - start_time
                    logger.info(
                        f"Resource {resource_type}/{resource_name} verified after {elapsed_time:.1f}s ({attempt} attempts)"
                    )
                    return True
            except Exception as e:
                logger.debug(f"Error verifying resource (attempt {attempt}): {e}")

        time.sleep(0.5)

    if log_found and resource_type and resource_name:
        logger.warning(
            f"Operator log found but {resource_type}/{resource_name} not verified after {timeout}s ({attempt} attempts)"
        )
    else:
        logger.warning(f"Operator log '{log_pattern}' for {actor_name} not found after {timeout}s ({attempt} attempts)")
    return False


def wait_for_asyncactor_ready(
    name: str,
    namespace: str = "asya-e2e",
    timeout: int = 60,
    required_conditions: list[str] | None = None,
    require_true: bool = True,
) -> bool:
    """
    Wait for AsyncActor to be ready by checking status conditions.

    Args:
        name: AsyncActor name
        namespace: Target namespace
        timeout: Maximum wait time in seconds
        required_conditions: List of condition types that must be present (default: ["WorkloadReady"])
        require_true: If True, wait for conditions to be True; if False, just wait for them to exist

    Returns:
        True if all required conditions meet criteria, False if timeout
    """
    if required_conditions is None:
        required_conditions = ["WorkloadReady"]

    logger.debug(
        f"Waiting for AsyncActor {name}: required_conditions={required_conditions}, require_true={require_true}"
    )

    start_time = time.time()
    attempt = 0
    last_actor_yaml = None

    while time.time() - start_time < timeout:
        attempt += 1
        try:
            result = subprocess.run(
                ["kubectl", "get", "asyncactor", name, "-n", namespace, "-o=json"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                logger.debug(f"Attempt {attempt}: kubectl get failed, returncode={result.returncode}")
                time.sleep(1)
                continue

            actor = yaml.safe_load(result.stdout)
            last_actor_yaml = result.stdout
            status = actor.get("status", {})
            conditions = status.get("conditions", [])

            logger.debug(f"Attempt {attempt}: Found {len(conditions)} conditions: {[c['type'] for c in conditions]}")

            all_ready = True
            missing_conditions = []
            false_conditions = []

            for required_type in required_conditions:
                condition = next((c for c in conditions if c["type"] == required_type), None)
                if not condition:
                    all_ready = False
                    missing_conditions.append(required_type)
                    logger.debug(f"Attempt {attempt}: Condition '{required_type}' not found")
                    break

                cond_status = condition.get("status")
                logger.debug(
                    f"Attempt {attempt}: Condition '{required_type}' status={cond_status}, require_true={require_true}"
                )

                if require_true and cond_status != "True":
                    all_ready = False
                    false_conditions.append(f"{required_type}={cond_status}")
                    logger.debug(f"Attempt {attempt}: Condition '{required_type}' is {cond_status}, need True")
                    break

            if all_ready:
                elapsed = time.time() - start_time
                status_desc = "True" if require_true else "present"
                logger.info(
                    f"AsyncActor {name} ready (conditions {status_desc}: {required_conditions}) after {elapsed:.1f}s ({attempt} attempts)"
                )
                return True
            else:
                if missing_conditions:
                    logger.debug(f"Attempt {attempt}: Missing conditions: {missing_conditions}")
                if false_conditions:
                    logger.debug(f"Attempt {attempt}: Conditions not True: {false_conditions}")

        except Exception as e:
            logger.debug(f"Attempt {attempt}: Exception: {e}")

        time.sleep(1)

    logger.warning(f"AsyncActor {name} not ready after {timeout}s ({attempt} attempts)")

    if last_actor_yaml:
        logger.debug(f"Last AsyncActor YAML:\n{last_actor_yaml}")

    return False
