"""
Test handler for integration tests.

Simple handler that echoes the payload with a "processed" marker.
"""

from typing import Any, Dict, List, Optional


def process(payload: Dict[str, Any], route: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Process the payload and return it with a "processed" marker.

    Args:
        payload: Payload dict
        route: Optional route parameter (unused)

    Returns:
        Processed result dict
    """

    return [
        {
            "payload": {
                "status": "processed",
                "original": payload,
                "message": "Integration test message processed successfully",
            },
            "route": {"actors": ["actor-1", "actor-2", "actor-3"], "current": 0},
        }
    ]
