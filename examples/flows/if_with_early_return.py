"""
Early return in conditional.

Tests early exit pattern with assert guard and module-level imports.
"""

from my_handlers import handler_validate, handler_process, handler_finalize


def early_return_flow(ctx: dict) -> dict:
    assert ctx.get("user_id"), "user_id is required"

    ctx = handler_validate(ctx)
    if not ctx["valid"]:
        ctx["error"] = "validation_failed"
        return ctx
    ctx = handler_process(ctx)
    ctx = handler_finalize(ctx)
    return ctx
