"""
Class-based test handlers for component and integration tests.

These handlers test stateful class handler functionality:
- Slow model initialization (simulates AI model loading)
- State preservation across requests (caching, counters)
- Large payload handling with stateful processing
- Deep module structures
"""

import time
from typing import Any


# Slow initialization handler
class SlowModelHandler:
    """Handler with slow initialization (simulates model loading)."""

    def __init__(self):
        time.sleep(2)  # Simulate 2s model loading
        self.init_time = time.time()
        self.call_count = 0

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
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


# Envelope mode handler
class EnvelopeHandler:
    """Handler that processes full envelopes."""

    def __init__(self):
        self.prefix = "processed"
        self.envelope_count = 0

    def process(self, envelope: dict[str, Any]) -> dict[str, Any]:
        self.envelope_count += 1

        # Access headers
        trace_id = envelope.get("headers", {}).get("trace_id", "unknown")

        return {
            "payload": {
                "prefix": self.prefix,
                "trace_id": trace_id,
                "data": envelope["payload"],
                "envelope_count": self.envelope_count,
            },
            "route": envelope["route"],
            "headers": envelope.get("headers", {}),
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
