"""E2E test helper with Kubernetes operations."""

import logging
import subprocess

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
        import time

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
