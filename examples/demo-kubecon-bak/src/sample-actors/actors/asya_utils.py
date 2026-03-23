from functools import wraps

def actor(func):
    """
    Decorator to drive an async generator handler,
    returning the single non-tuple event emitted.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)

        # Drive the generator and filter out ABI control events (tuples)
        events = [e async for e in gen if not isinstance(e, tuple)]

        if len(events) != 1:
            raise ValueError(f"Expected 1 emitted frame, got {len(events)}")

        return events[0]

    return wrapper
