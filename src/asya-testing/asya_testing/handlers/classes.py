"""
Class-based test handlers for component and integration tests.

These handlers test stateful class handler functionality:
- Slow model initialization (simulates AI model loading)
- State preservation across requests (caching, counters)
- Large payload handling with stateful processing
- Deep module structures
- Message metadata access (VFS, pending migration to ABI)

Async class methods (async def process) represent the preferred pattern
for AI workloads. __init__ is always synchronous.
"""

import os
import time
from typing import Any


ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")


# Slow initialization handler
class SlowModelHandler:
    """Handler with slow initialization (simulates model loading)."""

    def __init__(self):
        time.sleep(2)  # Simulate 2s model loading
        self.init_time = time.time()
        self.call_count = 0

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        return {
            "init_time": self.init_time,
            "call_count": self.call_count,
            "payload": payload,
        }


# Stateful cache handler
class CachingHandler:
    """Handler with growing cache (simulates embedding cache)."""

    def __init__(self):
        self.cache = {}
        self.cache_hits = 0
        self.cache_misses = 0

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = payload.get("key", "default")

        if key in self.cache:
            self.cache_hits += 1
            result = self.cache[key]
        else:
            self.cache_misses += 1
            # Simulate expensive computation
            result = f"computed_{key}"
            self.cache[key] = result

        return {
            "result": result,
            "cache_size": len(self.cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


# Large payload handler
class LargePayloadHandler:
    """Handler that generates large responses."""

    def __init__(self):
        self.request_count = 0

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.request_count += 1
        size_mb = payload.get("size_mb", 10)

        # Generate large response (~10MB)
        large_data = "X" * (size_mb * 1024 * 1024)

        return {
            "data": large_data,
            "size": len(large_data),
            "request_count": self.request_count,
        }


# Counter handler (for sequential state testing)
class CounterHandler:
    """Handler with simple counter for state preservation tests."""

    def __init__(self):
        self.count = 0
        self.requests = []

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload.get("request_id", "unknown")

        # Record request
        self.requests.append(request_id)

        # Increment counter
        self.count += 1

        return {
            "request_id": request_id,
            "count": self.count,
            "total_requests": len(self.requests),
        }


# VFS metadata handler
class MessageHandler:
    """Handler that accesses message metadata via VFS."""

    def __init__(self):
        self.prefix = "processed"
        self.message_count = 0

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.message_count += 1

        try:
            with open(f"{ASYA_MSG_ROOT}/headers/trace_id") as f:
                trace_id = f.read()
        except FileNotFoundError:
            trace_id = "unknown"

        return {
            "prefix": self.prefix,
            "trace_id": trace_id,
            "data": payload,
            "message_count": self.message_count,
        }


# Handler with default parameters
class ConfigurableHandler:
    """Handler with configurable initialization parameters."""

    def __init__(self, multiplier: int = 3, prefix: str = "result"):
        self.multiplier = multiplier
        self.prefix = prefix

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("value", 0)
        return {self.prefix: value * self.multiplier}
