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

    def __init__(self, gateway_url: str, namespace: str = "asya-e2e", progress_method: str = "sse"):
        super().__init__(gateway_url=gateway_url, progress_method=progress_method)
        self.namespace = namespace

    def kubectl(self, *args: str) -> str:
        """Execute kubectl command."""
        cmd = ["kubectl", "-n", self.namespace, *list(args)]
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
            label_selector: Kubernetes label selector (e.g., "app=my-app")
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

    def wait_for_envelope_completion(
        self,
        envelope_id: str,
        timeout: int = 20,
        interval: float = 0.5,
    ) -> dict:
        """
        Poll envelope status until it reaches end state.

        This E2E version handles connection errors by automatically restarting
        port-forward when needed (useful in chaos tests).

        Returns the final envelope object when status is succeeded, failed, or unknown.

        Raises:
            TimeoutError: If envelope doesn't complete within timeout
            ConnectionError: If gateway becomes unreachable after retries
        """
        logger.debug(f"Waiting for envelope completion: {envelope_id} (timeout={timeout}s)")
        start_time = time.time()
        consecutive_failures = 0
        max_consecutive_failures = 3

        i = 0
        while time.time() - start_time < timeout:
            try:
                envelope = self.get_envelope_status(envelope_id)
                consecutive_failures = 0

                elapsed = time.time() - start_time

                if envelope["status"] in ["succeeded", "failed", "unknown"]:
                    logger.info(f"Envelope completed after {elapsed:.2f}s with status: {envelope['status']}")
                    return envelope

                i += 1
                if i % int(5 / interval) == 0:
                    logger.debug(f"Envelope still {envelope['status']} after {elapsed:.2f}s, waiting...")

                time.sleep(interval)

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                consecutive_failures += 1
                logger.warning(
                    f"Connection error while checking envelope status (attempt {consecutive_failures}/{max_consecutive_failures}): {e}"
                )

                if consecutive_failures >= max_consecutive_failures:
                    logger.error("Too many consecutive connection failures, attempting port-forward restart")
                    try:
                        self.ensure_gateway_connectivity(max_retries=2)
                        consecutive_failures = 0
                        logger.info("Gateway connectivity restored, resuming envelope wait")
                    except ConnectionError as ce:
                        raise ConnectionError(
                            f"Gateway unreachable after port-forward restart while waiting for envelope {envelope_id}"
                        ) from ce

                time.sleep(interval)

        raise TimeoutError(f"Envelope {envelope_id} did not complete within {timeout}s")

    def ensure_gateway_connectivity(self, max_retries: int = 3) -> bool:
        """
        Ensure gateway is reachable, restarting port-forward if needed.

        This method checks gateway connectivity and automatically restarts
        port-forward if connection fails. Useful in chaos tests where
        infrastructure components restart and may break port-forward.

        Args:
            max_retries: Maximum number of retry attempts

        Returns:
            True if gateway is reachable, False otherwise

        Raises:
            ConnectionError: If gateway unreachable after all retries
        """
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{self.gateway_url}/health",
                    timeout=2,
                )
                if response.status_code == 200:
                    logger.debug("Gateway connectivity confirmed")
                    return True
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning(f"Gateway unreachable (attempt {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    logger.info("Restarting port-forward...")
                    if self.restart_port_forward():
                        time.sleep(3)
                    else:
                        logger.error("Failed to restart port-forward")
                        break

        raise ConnectionError(f"Gateway unreachable after {max_retries} attempts")

    def restart_port_forward(self, service_name: str = "asya-gateway", local_port: int = 8080):
        """
        Restart port-forward connection to a service.

        This is useful when the target pod is restarted and the port-forward connection breaks.

        Args:
            service_name: Name of the service to port-forward to
            local_port: Local port to forward to

        Returns:
            True if port-forward was successfully re-established
        """
        import os
        import signal

        logger.info(f"Restarting port-forward for {service_name}...")

        try:
            result = subprocess.run(
                ["pgrep", "-f", f"kubectl port-forward.*{service_name}.*{local_port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid_str in pids:
                    try:
                        pid = int(pid_str.strip())
                        os.kill(pid, signal.SIGTERM)
                        logger.debug(f"Killed existing port-forward PID {pid}")
                    except (ValueError, ProcessLookupError):
                        pass

                time.sleep(1)

        except Exception as e:
            logger.warning(f"Failed to kill existing port-forward: {e}")

        script_dir = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        port_forward_script = f"{script_dir}/testing/e2e/scripts/port-forward.sh"

        try:
            subprocess.run(
                [port_forward_script, "start"],
                env={**os.environ, "NAMESPACE": self.namespace},
                timeout=30,
                check=True,
            )
            logger.info(f"Port-forward re-established for {service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to restart port-forward: {e}")
            return False
