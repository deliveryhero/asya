"""
Pure sequential flow - no control structures.

Tests sequential handler execution with module-level imports.
"""

from my_handlers import handler_a, handler_b, handler_c


def sequential_flow(data: dict) -> dict:
    data = handler_a(data)
    data = handler_b(data)
    data = handler_c(data)
    return data
