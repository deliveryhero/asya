"""
Diagnostic helpers for E2E and integration tests.

Provides functions to log detailed status of Asya components during test execution.
"""

import logging
import subprocess


logger = logging.getLogger(__name__)


def run_kubectl(args: list, namespace: str = "asya-e2e") -> str | None:
    """Run kubectl command and return output."""
    cmd = ["kubectl", *args]
    if "-n" not in args and "--all-namespaces" not in args:
        cmd.extend(["-n", namespace])

    try:
        # nosemgrep: dangerous-subprocess-use-audit
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        else:
            logger.warning(f"kubectl command failed: {' '.join(cmd)}")
            logger.warning(f"stderr: {result.stderr}")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"kubectl command timed out: {' '.join(cmd)}")
        return None
    except Exception as e:
        logger.warning(f"kubectl command error: {e}")
        return None


def log_pod_status(pod_label: str, component_name: str, namespace: str = "asya-e2e"):
    """Log status of pods matching a label selector."""
    logger.info(f"--- {component_name} Pod Status ---")
    output = run_kubectl(["get", "pods", "-l", pod_label, "-o", "wide"], namespace)
    if output:
        logger.info(f"\n{output}")
    else:
        logger.warning(f"[!] No pods found for {component_name} (label: {pod_label})")


def log_deployment_status(deployment_name: str, namespace: str = "asya-e2e"):
    """Log status of a deployment."""
    logger.info(f"--- Deployment: {deployment_name} ---")
    output = run_kubectl(["get", "deployment", deployment_name, "-o", "wide"], namespace)
    if output:
        logger.info(f"\n{output}")
    else:
        logger.warning(f"[!] Deployment {deployment_name} not found")


def log_pod_logs(pod_label: str, component_name: str, namespace: str = "asya-e2e", tail: int = 20):
    """Log recent logs from pods matching a label selector."""
    logger.info(f"--- {component_name} Recent Logs (tail={tail}) ---")
    output = run_kubectl(["logs", "-l", pod_label, f"--tail={tail}"], namespace)
    if output:
        logger.info(f"\n{output}")
    else:
        logger.warning(f"[!] No logs found for {component_name} (label: {pod_label})")


def log_scaledobjects(namespace: str = "asya-e2e"):
    """Log KEDA ScaledObject status."""
    logger.info("--- KEDA ScaledObjects ---")
    output = run_kubectl(["get", "scaledobject", "-o", "wide"], namespace)
    if output:
        logger.info(f"\n{output}")
    else:
        logger.warning("[!] No ScaledObjects found")


def log_asyncactors(namespace: str = "asya-e2e"):
    """Log AsyncActor CRD status."""
    logger.info("--- AsyncActor CRDs ---")
    output = run_kubectl(["get", "asyncactor", "-o", "wide"], namespace)
    if output:
        logger.info(f"\n{output}")
    else:
        logger.warning(f"[!] No AsyncActors found in namespace {namespace}")


def log_rabbitmq_queues(
    mgmt_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
):
    """
    Log RabbitMQ queue status via management API.

    Args:
        mgmt_url: RabbitMQ management API URL (if None, uses RABBITMQ_MGMT_URL env var)
        username: RabbitMQ username (if None, uses RABBITMQ_USER env var)
        password: RabbitMQ password (if None, uses RABBITMQ_PASS env var)
    """
    import requests

    from asya_testing.config import get_env

    mgmt_url = mgmt_url or get_env("RABBITMQ_MGMT_URL", "")
    username = username or get_env("RABBITMQ_USER", "guest")
    password = password or get_env("RABBITMQ_PASS", "guest")

    if not mgmt_url:
        logger.info("--- RabbitMQ Queue Status ---")
        logger.info("[.] RABBITMQ_MGMT_URL not set, skipping RabbitMQ diagnostics")
        return

    logger.info("--- RabbitMQ Queue Status ---")
    try:
        response = requests.get(f"{mgmt_url}/api/queues", auth=(username, password), timeout=5)
        if response.status_code == 200:
            queues = response.json()
            if not queues:
                logger.info("[.] No queues found")
            for queue in queues:
                logger.info(
                    f"Queue: {queue['name']}, Messages: {queue.get('messages', 0)}, "
                    f"Consumers: {queue.get('consumers', 0)}"
                )
        elif response.status_code == 401:
            logger.warning(f"[!] RabbitMQ API authentication failed (status {response.status_code})")
            logger.warning("    Check RABBITMQ_USER and RABBITMQ_PASS environment variables")
        else:
            logger.warning(f"[!] RabbitMQ API returned status {response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.warning(f"[!] Could not connect to RabbitMQ management API at {mgmt_url}")
        logger.warning("    Ensure RabbitMQ is running with management plugin enabled")
        logger.warning("    Check that port-forwarding is active (kubectl port-forward svc/asya-rabbitmq 15672:15672)")
    except Exception as e:
        logger.warning(f"[!] Could not fetch RabbitMQ queues: {e}")


def log_recent_events(namespace: str = "asya-e2e", count: int = 20):
    """Log recent Kubernetes events."""
    logger.info(f"--- Recent Events (last {count}) ---")
    output = run_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace)
    if output:
        lines = output.strip().split("\n")
        recent_lines = lines[-count:] if len(lines) > count else lines
        logger.info("\n" + "\n".join(recent_lines))
    else:
        logger.warning("[!] No events found")


def check_actor_readiness(actor_name: str, namespace: str = "asya-e2e") -> dict:
    """
    Check if an actor is ready to process messages.

    Returns dict with diagnostic info:
    - asyncactor_exists: bool
    - deployment_exists: bool
    - deployment_ready: bool
    - replicas: int
    - ready_replicas: int
    - scaledobject_exists: bool
    - scaledobject_ready: bool
    - queue_exists: bool
    - queue_consumers: int
    - pod_status: str (Running, Pending, CrashLoopBackOff, etc)
    - recent_errors: list[str]
    """
    result = {
        "actor_name": actor_name,
        "asyncactor_exists": False,
        "deployment_exists": False,
        "deployment_ready": False,
        "replicas": 0,
        "ready_replicas": 0,
        "scaledobject_exists": False,
        "scaledobject_ready": False,
        "queue_exists": False,
        "queue_consumers": 0,
        "pod_status": "Unknown",
        "recent_errors": [],
    }

    # Check AsyncActor CRD
    output = run_kubectl(["get", "asyncactor", actor_name], namespace)
    result["asyncactor_exists"] = output is not None

    # Check Deployment
    output = run_kubectl(
        ["get", "deployment", actor_name, "-o", "jsonpath={.status.replicas},{.status.readyReplicas}"], namespace
    )
    if output:
        result["deployment_exists"] = True
        parts = output.split(",")
        replicas = int(parts[0]) if parts[0] else 0
        ready_replicas = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        result["replicas"] = replicas
        result["ready_replicas"] = ready_replicas
        result["deployment_ready"] = replicas > 0 and replicas == ready_replicas

    # Check ScaledObject
    output = run_kubectl(
        ["get", "scaledobject", actor_name, "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"], namespace
    )
    if output:
        result["scaledobject_exists"] = True
        result["scaledobject_ready"] = output.strip() == "True"

    # Check pod status
    output = run_kubectl(
        ["get", "pods", "-l", f"asya.sh/asya={actor_name}", "-o", "json"],
        namespace,
    )
    if output:
        import json

        try:
            pod_list = json.loads(output)
            if pod_list.get("items"):
                result["pod_status"] = pod_list["items"][0].get("status", {}).get("phase", "Unknown")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    # Check RabbitMQ queue (if available)
    try:
        import requests

        from asya_testing.config import get_env

        mgmt_url = get_env("RABBITMQ_MGMT_URL", "")
        if mgmt_url:
            username = get_env("RABBITMQ_USER", "guest")
            password = get_env("RABBITMQ_PASS", "guest")
            response = requests.get(f"{mgmt_url}/api/queues/%2F/{actor_name}", auth=(username, password), timeout=5)
            if response.status_code == 200:
                queue_data = response.json()
                result["queue_exists"] = True
                result["queue_consumers"] = queue_data.get("consumers", 0)
    except Exception:
        pass

    # Check recent pod errors
    output = run_kubectl(["logs", "-l", f"asya.sh/asya={actor_name}", "--tail=50", "-c", "sidecar"], namespace)
    if output:
        errors = [line for line in output.split("\n") if "ERROR" in line or "FATAL" in line or "panic" in line]
        result["recent_errors"] = errors[-5:] if len(errors) > 5 else errors

    return result


def log_actor_diagnostics(actor_name: str, namespace: str = "asya-e2e"):
    """Log detailed diagnostics for a specific actor."""
    logger.info(f"\n{'=' * 80}")
    logger.info(f"=== Actor Diagnostics: {actor_name} ===")
    logger.info("=" * 80)

    info = check_actor_readiness(actor_name, namespace)

    logger.info(f"AsyncActor CRD exists: {info['asyncactor_exists']}")
    logger.info(f"Deployment exists: {info['deployment_exists']}")
    if info["deployment_exists"]:
        logger.info(f"  Replicas: {info['replicas']}, Ready: {info['ready_replicas']}")
        logger.info(f"  Deployment ready: {info['deployment_ready']}")
    logger.info(f"ScaledObject exists: {info['scaledobject_exists']}")
    if info["scaledobject_exists"]:
        logger.info(f"  ScaledObject ready: {info['scaledobject_ready']}")
    logger.info(f"Pod status: {info['pod_status']}")
    logger.info(f"Queue exists: {info['queue_exists']}")
    if info["queue_exists"]:
        logger.info(f"  Queue consumers: {info['queue_consumers']}")

    if info["recent_errors"]:
        logger.warning(f"Recent errors found ({len(info['recent_errors'])}):")
        for error in info["recent_errors"]:
            logger.warning(f"  {error}")

    # Show detailed pod logs if actor is not ready
    if not info["deployment_ready"] or info["queue_consumers"] == 0:
        log_pod_logs(f"asya.sh/asya={actor_name}", f"{actor_name} (Not Ready)", namespace, tail=30)

    logger.info("=" * 80 + "\n")


def log_full_e2e_diagnostics(namespace: str | None = None, transport: str | None = None):
    """
    Log comprehensive diagnostics of all Asya components.

    Args:
        namespace: Kubernetes namespace to use for E2E components (default: from NAMESPACE env var or "asya-e2e")
        transport: Transport type (default: from ASYA_TRANSPORT env var). Used to skip irrelevant diagnostics
    """
    import os

    if namespace is None:
        namespace = os.getenv("NAMESPACE", "asya-e2e")

    logger.info("\n" + "=" * 80)
    logger.info("=== Pre-Test Diagnostics ===")
    logger.info(f"=== Namespace: {namespace} ===")
    logger.info("=" * 80)

    # Operator
    log_deployment_status("asya-operator", "asya-system")
    log_pod_status("app.kubernetes.io/name=asya-operator", "Operator", "asya-system")

    # Gateway
    log_deployment_status("asya-gateway", namespace)
    log_pod_status("app.kubernetes.io/name=asya-gateway", "Gateway", namespace)

    # Infrastructure
    if transport == "rabbitmq":
        log_pod_status("app=rabbitmq", "RabbitMQ", namespace)
        log_rabbitmq_queues()
    log_pod_status("app=postgresql", "PostgreSQL", namespace)

    # KEDA
    log_scaledobjects(namespace)

    # AsyncActors
    log_asyncactors(namespace)

    # Recent events
    log_recent_events(namespace)

    logger.info("=" * 80)
    logger.info("=== End Pre-Test Diagnostics ===")
    logger.info("=" * 80 + "\n")


def log_test_failure_diagnostics(
    test_name: str,
    actors: list[str] | None = None,
    namespace: str = "asya-e2e",
    transport: str | None = None,
):
    """
    Log diagnostics specific to a failed test.

    Args:
        test_name: Name of the failed test
        actors: List of actor names involved in the test (will diagnose these specifically)
        namespace: Kubernetes namespace
        transport: Transport type (default: from ASYA_TRANSPORT env var). Used to skip irrelevant diagnostics
    """
    logger.info("\n" + "=" * 80)
    logger.info(f"=== Test Failure Diagnostics: {test_name} ===")
    logger.info("=" * 80)

    # If specific actors provided, diagnose them in detail
    if actors:
        for actor in actors:
            log_actor_diagnostics(actor, namespace)

    # Gateway logs (last 50 lines)
    log_pod_logs("app.kubernetes.io/name=asya-gateway", "Gateway (Failure Context)", namespace, tail=50)

    # RabbitMQ queues
    if transport == "rabbitmq":
        log_rabbitmq_queues()

    # Recent events (last 30)
    log_recent_events(namespace, count=30)

    logger.info("=" * 80)
    logger.info("=== End Test Failure Diagnostics ===")
    logger.info("=" * 80 + "\n")
