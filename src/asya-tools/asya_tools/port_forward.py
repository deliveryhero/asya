#!/usr/bin/env python3
"""
Quick kubectl port-forward helper for asya gateway MCP access.

Finds a free local port, forwards to asya-gateway, and outputs the URL.
All logs go to stderr, only URL goes to stdout for easy env var capture.

Usage:
    export ASYA_TOOLS_MCP_URL=$(asya-mcp-forward)
    asya-mcp list

    export ASYA_TOOLS_MCP_URL=$(asya-mcp-forward --namespace my-ns)
    asya-mcp call echo --message hello

Options:
    --namespace, -n      Kubernetes namespace (default: asya-e2e)
    --deployment, -d     Deployment name (default: asya-gateway)
    --port, -p          Target port (default: 8080)
    --local-port, -l    Local port (default: auto-detect free port)
    --check-health      Verify gateway health endpoint (default: true)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import socket
import subprocess  # nosec B404
import sys
import time
import traceback
from typing import NoReturn


def find_free_port(start: int = 8080, end: int = 9000) -> int:
    """Find a free local port in range [start, end]."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    print(f"[-] No free ports found in range {start}-{end}", file=sys.stderr)
    sys.exit(1)


def check_port_available(port: int) -> bool:
    """Check if port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def check_health(port: int, timeout: int = 5) -> bool:
    """Check if gateway health endpoint responds."""
    try:
        import requests

        url = f"http://localhost:{port}/health"
        print(f"[.] Checking health: GET {url}", file=sys.stderr)
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return True
        print(f"[!] Health check failed: HTTP {resp.status_code}", file=sys.stderr)
        print(f"[!] Response body: {resp.text[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[!] Health check failed: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"[!] Traceback:\n{traceback.format_exc()}", file=sys.stderr)
        return False


def find_existing_port_forward(namespace: str, deployment: str) -> int | None:
    """Check if port-forward is already running and return local port."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["pgrep", "-f", f"kubectl port-forward.*{namespace}.*{deployment}"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return None

        pid = result.stdout.strip().split("\n")[0]
        if not pid:
            return None

        cmdline_result = subprocess.run(  # nosec B603 B607
            ["ps", "-p", pid, "-o", "args="], capture_output=True, text=True, check=False
        )

        if cmdline_result.returncode != 0:
            return None

        cmdline = cmdline_result.stdout.strip()

        parts = cmdline.split()
        for part in parts:
            if ":" in part and not part.startswith("--"):
                local_port_str = part.split(":")[0]
                try:
                    return int(local_port_str)
                except ValueError:
                    continue

        return None

    except Exception:
        return None


def kill_existing_port_forward(namespace: str, deployment: str) -> None:
    """Kill existing port-forward process."""
    try:
        subprocess.run(  # nosec B603 B607
            ["pkill", "-f", f"kubectl port-forward.*{namespace}.*{deployment}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
    except Exception:  # nosec B110
        pass


def start_port_forward(
    namespace: str, deployment: str, local_port: int, remote_port: int, check_health_enabled: bool = True
) -> subprocess.Popen[bytes]:
    """Start kubectl port-forward in background."""
    cmd = [
        "kubectl",
        "port-forward",
        "-n",
        namespace,
        "--pod-running-timeout=5m",
        f"deployment/{deployment}",
        f"{local_port}:{remote_port}",
    ]

    print(f"[.] Starting port-forward: {' '.join(cmd)}", file=sys.stderr)

    process = subprocess.Popen(  # nosec B603
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid
    )

    print(f"[.] Port-forward started with PID {process.pid}", file=sys.stderr)

    if check_health_enabled:
        print("[.] Waiting for gateway to be ready...", file=sys.stderr)
        for attempt in range(1, 6):
            time.sleep(1)

            # Check if port-forward process is still alive
            poll_result = process.poll()
            if poll_result is not None:
                print(f"[-] Port-forward process died with exit code {poll_result}", file=sys.stderr)
                print(
                    f"[!] This usually means the deployment '{deployment}' doesn't exist in namespace '{namespace}'",
                    file=sys.stderr,
                )
                sys.exit(1)

            if check_health(local_port):
                print(f"[+] Gateway health check passed (attempt {attempt}/5)", file=sys.stderr)
                return process
            print(f"[.] Health check attempt {attempt}/5 failed, retrying...", file=sys.stderr)

        print("[-] Gateway health check failed after 5 attempts", file=sys.stderr)
        print(
            f"[!] Port-forward process status: {'running' if process.poll() is None else 'dead'}",
            file=sys.stderr,
        )
        print(
            f"[!] Possible causes: gateway pod not ready, wrong port ({remote_port}), no /health endpoint",
            file=sys.stderr,
        )
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        sys.exit(1)
    else:
        time.sleep(2)

    return process


def cleanup_on_exit(process: subprocess.Popen[bytes]) -> NoReturn:
    """Clean up port-forward process on exit."""

    def signal_handler(signum: int, _frame: object) -> NoReturn:
        print("[.] Received signal, cleaning up port-forward...", file=sys.stderr)
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
            print("[+] Port-forward stopped", file=sys.stderr)
        except Exception as e:
            print(f"[!] Error during cleanup: {e}", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        process.wait()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="kubectl port-forward helper for asya gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--namespace", "-n", default="asya-e2e", help="Kubernetes namespace (default: asya-e2e)")
    parser.add_argument("--deployment", "-d", default="asya-gateway", help="Deployment name (default: asya-gateway)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Target port (default: 8080)")
    parser.add_argument(
        "--local-port", "-l", type=int, default=None, help="Local port (default: auto-detect free port)"
    )
    parser.add_argument(
        "--check-health",
        action="store_true",
        default=True,
        help="Verify gateway health endpoint (default: true)",
    )
    parser.add_argument("--no-check-health", dest="check_health", action="store_false", help="Skip health check")
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        default=False,
        help="Keep port-forward running until interrupted (default: false)",
    )

    args = parser.parse_args()

    existing_port = find_existing_port_forward(args.namespace, args.deployment)

    if existing_port:
        if args.check_health and check_health(existing_port):
            print(f"[+] Port-forward already running on htlocalhost:{existing_port} (healthy)", file=sys.stderr)
            print(f"http://localhost:{existing_port}")
            return
        else:
            print(
                f"[!] Port-forward found on localhost:{existing_port} but not healthy, kill...",
                file=sys.stderr,
            )
            kill_existing_port_forward(args.namespace, args.deployment)

    local_port = args.local_port if args.local_port else find_free_port()

    if not check_port_available(local_port):
        print(f"[-] Port {local_port} is already in use", file=sys.stderr)
        sys.exit(1)

    process = start_port_forward(args.namespace, args.deployment, local_port, args.port, args.check_health)

    url = f"http://localhost:{local_port}"
    print(
        f"[+] Port-forward active: localhost:{local_port} -> {args.deployment}.{args.namespace}:{args.port}",
        file=sys.stderr,
    )
    print(url)

    if args.keep_alive:
        print("[.] Port-forward is running. Press Ctrl+C to stop.", file=sys.stderr)
        cleanup_on_exit(process)


if __name__ == "__main__":
    main()
