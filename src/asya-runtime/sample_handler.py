"""
Test handler for integration tests.

Simple handler that echoes the payload with a "processed" marker.
"""


def process(payload: dict, route=None) -> dict:
    """
    Process the message payload and return it with a "processed" marker.

    Args:
        payload: Message payload dict

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
            "route": ["step-1", "step-2", "step-3"],
        }
    ]
