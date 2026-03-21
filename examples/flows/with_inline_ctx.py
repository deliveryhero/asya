"""Flow example: inline context manager (treat-as: inline).

When a context manager has `treat-as: inline` in the compiler rules, the
generated router wraps its routing decisions inside a `with expr:` block.
The `with` wrapper appears in the router's Python code and runs within the
router actor process -- it does NOT wrap the actual actor execution (which
happens in separate pods).

`contextlib.suppress` is a built-in inline rule: it suppresses the listed
exceptions inline in the router function, useful when optional routing
decisions may raise non-critical errors that should be silently ignored.

Compile with:
    asya flow compile with_inline_ctx.py --output-dir compiled/
"""

import contextlib

from _asya_utils import flow


@flow
def order_processing(p: dict) -> dict:
    p["stage"] = "validation"

    with contextlib.suppress(KeyError):
        p = validate_order(p)

    if p.get("valid"):
        p = payment_processor(p)
    else:
        p["status"] = "rejected"
        return p

    p["stage"] = "fulfillment"
    p = fulfillment_handler(p)
    return p
