"""E2E test helper with Kubernetes operations."""

import logging
import subprocess
import time

import requests
from asya_testing.utils.gateway import GatewayTestHelper
from asya_testing.utils.kubectl import (
    delete_pod as kubectl_delete_pod,
)
from asya_testing.utils.kubectl import (
    get_pod_count as kubectl_get_pod_count,
)
from asya_testing.utils.kubectl import (
    wait_for_pod_ready as kubectl_wait_for_pod_ready,
)


logger = logging.getLogger(__name__)


class E2ETestHelper(GatewayTestHelper):
    """
    E2E test helper that extends GatewayTestHelper with Kubernetes operations.

    Inherits all gateway functionality from GatewayTestHelper and adds:
    - kubectl operations for pod management
    - KEDA scaling checks
    - Pod readiness checks
    - RabbitMQ queue monitoring
    """

    def __init__(
        self,
        gateway_url: str,
        namespace: str = "asya-e2e",
        system_namespace: str = "asya-system",
        progress_method: str = "sse",
    ):
        super().__init__(gateway_url=gateway_url, progress_method=progress_method)
        self.namespace = namespace
        self.system_namespace = system_namespace

    def kubectl(self, *args: str, namespace: str | None = None) -> str:
        """Execute kubectl command.

        Args:
            *args: kubectl command arguments
            namespace: Optional namespace override. If not provided, uses self.namespace
        """
        target_namespace = namespace or self.namespace
        cmd = ["kubectl", "-n", target_namespace, *list(args)]
        logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"kubectl failed: {result.stderr}")
            raise RuntimeError(f"kubectl command failed: {result.stderr}")

        return result.stdout.strip()

    def get_pod_count(self, label_selector: str) -> int:
        """Get number of running pods matching label selector."""
        return kubectl_get_pod_count(label_selector, namespace=self.namespace)

    def delete_pod(self, pod_name: str):
        """Delete a pod to simulate crash/restart."""
        kubectl_delete_pod(pod_name, namespace=self.namespace, force=True)

    def wait_for_pod_ready(self, label_selector: str, timeout: int = 60, poll_interval: float = 1.0) -> bool:
        """
        Wait for at least one pod matching label selector to be ready.

        Args:
            label_selector: Kubernetes label selector (e.g., "asya.sh/actor=my-actor")
            timeout: Maximum time to wait in seconds
            poll_interval: Polling interval in seconds

        Returns:
            True if pod is ready, False if timeout
        """
        return kubectl_wait_for_pod_ready(
            label_selector, namespace=self.namespace, timeout=timeout, poll_interval=poll_interval
        )

    def get_rabbitmq_queue_length(self, queue_name: str, mgmt_url: str) -> int:
        """Get RabbitMQ queue message count."""
        try:
            response = requests.get(
                f"{mgmt_url}/api/queues/%2F/{queue_name}",
                auth=("guest", "guest"),
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("messages", 0)
            else:
                return 0
        except Exception as e:
            logger.warning(f"Failed to get queue length: {e}")
            return 0

    def wait_for_task_completion(
        self,
        task_id: str,
        timeout: int = 20,
        interval: float = 0.5,
    ) -> dict:
        """
        Poll task status until it reaches end state.

        This E2E version retries on transient connection errors (e.g. gateway
        pod restart during chaos tests).

        Returns the final task object when status is succeeded, failed, or unknown.

        Raises:
            TimeoutError: If task doesn't complete within timeout
            ConnectionError: If gateway becomes unreachable after retries
        """
        logger.debug(f"Waiting for task completion: {task_id} (timeout={timeout}s)")
        start_time = time.time()
        consecutive_failures = 0
        max_consecutive_failures = 5

        i = 0
        while time.time() - start_time < timeout:
            try:
                task = self.get_task_status(task_id)
                consecutive_failures = 0

                elapsed = time.time() - start_time

                if task["status"] in ["succeeded", "failed", "unknown"]:
                    logger.info(f"Task completed after {elapsed:.2f}s with status: {task['status']}")
                    return task

                i += 1
                every_5s = int(5 / interval)
                every_30s = int(30 / interval)
                if every_30s > 0 and i % every_30s == 0:
                    logger.info(f"Task {task_id} still {task['status']} after {elapsed:.1f}s")
                elif every_5s > 0 and i % every_5s == 0:
                    logger.debug(f"Task still {task['status']} after {elapsed:.2f}s, waiting...")

                time.sleep(interval)

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                consecutive_failures += 1
                logger.warning(
                    f"Connection error while checking task status (attempt {consecutive_failures}/{max_consecutive_failures}): {e}"
                )

                if consecutive_failures >= max_consecutive_failures:
                    raise ConnectionError(
                        f"Gateway unreachable after {max_consecutive_failures} consecutive failures "
                        f"while waiting for task {task_id}"
                    ) from e

                time.sleep(interval)

        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    def ensure_gateway_connectivity(self, max_retries: int = 3, retry_interval: float = 2.0) -> bool:
        """
        Wait for gateway to become reachable (e.g. after pod restart).

        In split deployments (api + mesh), checks both endpoints since they run
        as separate pods and may restart independently.

        Args:
            max_retries: Maximum number of retry attempts
            retry_interval: Seconds between retries

        Returns:
            True if gateway is reachable

        Raises:
            ConnectionError: If gateway unreachable after all retries
        """
        health_urls = [f"{self.gateway_url}/health"]
        if self.mesh_gateway_url != self.gateway_url:
            health_urls.append(f"{self.mesh_gateway_url}/health")

        for attempt in range(max_retries):
            try:
                for url in health_urls:
                    response = requests.get(url, timeout=2)
                    if response.status_code != 200:
                        raise requests.exceptions.ConnectionError(f"Gateway returned {response.status_code}: {url}")
                logger.debug("Gateway connectivity confirmed")
                return True
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning(f"Gateway unreachable (attempt {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    time.sleep(retry_interval)

        raise ConnectionError(f"Gateway unreachable after {max_retries} attempts")
