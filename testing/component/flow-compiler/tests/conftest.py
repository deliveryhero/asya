"""Pytest configuration for flow-compiler component tests."""

import copy
import re
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """
    Return the project root directory using git rev-parse.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def _make_msg_ctx(route_next=None):
    """Create a message context dict for ABI-based tests."""
    return {
        "id": "test-id",
        "route": {"prev": [], "next": route_next or []},
        "headers": {},
    }


def _set_path(data, path, value):
    """Set a value at a dotted path on a nested dict."""
    parts = path.lstrip(".").split(".")
    cur = data
    last = parts[-1]
    for p in parts[:-1]:
        cur = cur[p]
    m = re.match(r"^(\w+)\[(-?\d*):(-?\d*)\]$", last)
    if m:
        key = m.group(1)
        start = int(m.group(2)) if m.group(2) else None
        stop = int(m.group(3)) if m.group(3) else None
        cur[key][start:stop] = value
    else:
        cur[last] = value


def _resolve_path(data, path):
    """Resolve a dotted path on a nested dict."""
    parts = path.lstrip(".").split(".")
    cur = data
    for p in parts:
        cur = cur[p]
    return copy.deepcopy(cur)


def _del_path(data, path):
    """Delete a value at a dotted path on a nested dict."""
    parts = path.lstrip(".").split(".")
    cur = data
    for p in parts[:-1]:
        cur = cur[p]
    del cur[parts[-1]]


def _drive_abi(gen, msg_ctx):
    """Drive an ABI generator, return list of yielded payloads."""
    payloads = []
    value = None
    try:
        value = gen.send(None)
        while True:
            if (
                isinstance(value, tuple)
                and len(value) >= 2
                and isinstance(value[0], str)
                and value[0] in ("GET", "SET", "DEL")
            ):
                op = value[0]
                if op == "GET":
                    result = _resolve_path(msg_ctx, value[1])
                    value = gen.send(result)
                elif op == "SET":
                    _set_path(msg_ctx, value[1], value[2])
                    value = gen.send(None)
                elif op == "DEL":
                    _del_path(msg_ctx, value[1])
                    value = gen.send(None)
            else:
                payloads.append(value)
                value = gen.send(None)
    except StopIteration:
        pass
    return payloads


class AbiFrame:
    """A yielded payload frame with its route and header state snapshot."""

    def __init__(self, payload, route_next, headers):
        self.payload = payload
        self.route_next = list(route_next)
        self.headers = copy.deepcopy(headers)


def _drive_abi_multi(gen, msg_ctx):
    """Drive an ABI generator, return list of AbiFrame capturing state at each yield."""
    frames = []
    value = None
    try:
        value = gen.send(None)
        while True:
            if (
                isinstance(value, tuple)
                and len(value) >= 2
                and isinstance(value[0], str)
                and value[0] in ("GET", "SET", "DEL")
            ):
                op = value[0]
                if op == "GET":
                    result = _resolve_path(msg_ctx, value[1])
                    value = gen.send(result)
                elif op == "SET":
                    _set_path(msg_ctx, value[1], value[2])
                    value = gen.send(None)
                elif op == "DEL":
                    _del_path(msg_ctx, value[1])
                    value = gen.send(None)
            else:
                frames.append(
                    AbiFrame(
                        payload=value,
                        route_next=msg_ctx.get("route", {}).get("next", []),
                        headers=msg_ctx.get("headers", {}),
                    )
                )
                value = gen.send(None)
    except StopIteration:
        pass
    return frames
