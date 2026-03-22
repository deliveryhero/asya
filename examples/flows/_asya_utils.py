# No-op decorators — purely syntactical annotations for the compiler.
# The compiler identifies functions by decorator name (configurable in
# .asya/config.yaml). You can define your own decorators with the same
# names; the compiler only cares about the name, not the implementation.
#
# For real deployments, use the actual libraries (tenacity, asyncio, etc.)
# and let the runtime strip extracted decorators via ASYA_IGNORE_DECORATORS.


def flow(f):
    """Mark a function as a flow entrypoint."""
    return f


def actor(f):
    """Mark a function as an actor handler (not inlined by the compiler)."""
    return f


def inline(f):
    """Mark a function as inline code (runs inside the router, not a separate actor)."""
    return f
