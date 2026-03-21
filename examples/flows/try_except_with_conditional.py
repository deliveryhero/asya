"""
Try-except combined with conditional branching.

Demonstrates error handling around a conditional flow. Both branches
of the if/else are protected by the same try/except block, and the
finally block runs regardless of which branch was taken or whether
an error occurred.
"""

from _asya_utils import flow


@flow
def payment_flow(p: dict) -> dict:
    p = validate_payment(p)
    try:
        if p["method"] == "card":
            p = charge_card(p)
        else:
            p = process_bank_transfer(p)
        p = record_transaction(p)
    except ValueError:
        p["status"] = "payment_failed"
        p = notify_payment_failure(p)
    finally:
        p = audit_log(p)
    p = send_receipt(p)
    return p
