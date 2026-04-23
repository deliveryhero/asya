---
description: "Error handling usage: try/except in flows, error routing patterns, finally blocks"
---

# Error Handling in Flows

How to use `try/except/finally` in the Flow DSL to handle errors
declaratively. The compiler transforms Python error-handling syntax
into sidecar-native routing rules — no centralized error dispatch needed.

---

## How it works

When you write `try/except` in a flow, the compiler does three things:

1. **Generates except_routers** — one per `except` clause, each with a
   static route to the handler's continuation path
2. **Injects resiliency rules** into the manifests of every actor inside
   the `try` body, so the sidecar routes errors to the correct except_router
3. **Includes `finally` actors** in both the success path and every
   error handler's path

The sidecar matches errors using first-match rules against the error's
type and MRO (method resolution order). No Python-level `isinstance()`
checks — error dispatch is fully declarative.

---

## Simple try/except

Catch a specific exception and route to a handler actor:

```python
from asya_lab.flow import flow

@flow
def order_processing(p: dict) -> dict:
    try:
        p = validate_order(p)
    except ValueError:
        p["status"] = "invalid"
        p = notify_rejection(p)
    return p
```

**What happens at runtime:**

```
                       envelope
                          │
                 ┌────────▼────────┐
                 │ validate_order  │
                 └──┬───────────┬──┘
              OK    │           │  ValueError
                    │           │
                    │    ┌──────▼─────────────────────┐
                    │    │      *except_router*       │
                    │    │  SET route.next=[seq, ...] │
                    │    └──────┬─────────────────────┘
                    │           │
                    │    ┌──────▼───────────────┐
                    │    │  *notify_rejection*  │
                    │    │ p["status"]="invalid"│
                    │    └──────┬───────────────┘
                    │           │
                    └─────┬─────┘
                          │
                     ┌────▼────┐
                     │ x-sink  │
                     └─────────┘
```

The sidecar on `validate-order`'s pod has a resiliency rule:

```yaml
resiliency:
  policies:
    try_except_line_4_0:
      maxAttempts: 1
      thenRoute: ["router-order-processing-line-6-except-2"]
  rules:
    - errors: ["ValueError"]
      policy: try_except_line_4_0
```

When `validate_order` throws `ValueError`, the sidecar matches the rule
and routes to the except_router. The except_router overwrites `route.next`
with the handler path. `validate_order` is not retried (maxAttempts: 1).

---

## Multiple except handlers

Each `except` clause generates its own router and resiliency rule:

```python
@flow
def data_pipeline(p: dict) -> dict:
    try:
        p = parse_input(p)
        p = transform_data(p)
    except ValueError:
        p["error_type"] = "validation"
        p = handle_validation_error(p)
    except TypeError:
        p["error_type"] = "type_mismatch"
        p = handle_type_error(p)
    return p
```

Both `parse_input` and `transform_data` get **two** resiliency rules
(one per handler). The sidecar evaluates rules top-to-bottom, first match
wins:

```yaml
# Injected into parse_input AND transform_data manifests:
resiliency:
  policies:
    try_except_line_4_0: { maxAttempts: 1, thenRoute: [except-router-ve] }
    try_except_line_4_1: { maxAttempts: 1, thenRoute: [except-router-te] }
  rules:
    - errors: ["ValueError"]
      policy: try_except_line_4_0
    - errors: ["TypeError"]
      policy: try_except_line_4_1
```

---

## Tuple exception types

Catch multiple exception types in a single handler:

```python
@flow
def ingestion_pipeline(p: dict) -> dict:
    try:
        p = fetch_data(p)
    except (ConnectionError, TimeoutError):
        p["retry_reason"] = "transient"
        p = queue_for_retry(p)
    return p
```

The generated rule has multiple entries in `errors`:

```yaml
rules:
  - errors: ["ConnectionError", "TimeoutError"]
    policy: try_except_line_3_0
```

---

## FQN exception types

Catch vendor-specific exceptions using fully-qualified names:

```python
@flow
def llm_pipeline(p: dict) -> dict:
    try:
        p = call_llm(p)
    except openai.RateLimitError:
        p = call_fallback_llm(p)
    except openai.AuthenticationError:
        p = notify_admin(p)
    return p
```

The sidecar matches FQN types exactly: `openai.RateLimitError` only
matches errors where `type.__module__ + "." + type.__name__` equals
`"openai.RateLimitError"`. Short names (no dot) match any error with
that `type.__name__`.

---

## try/except/finally

`finally` actors run on both success and error paths:

```python
@flow
def resource_pipeline(p: dict) -> dict:
    try:
        p = acquire_resource(p)
        p = process_with_resource(p)
    except RuntimeError:
        p["status"] = "failed"
        p = handle_failure(p)
    finally:
        p = release_resource(p)
    p = finalize(p)
    return p
```

**Success path:**

```
acquire_resource → process_with_resource → release_resource → finalize
```

**Error path (RuntimeError in either actor):**

```
except_router → p["status"]="failed" → handle_failure → release_resource → finalize
```

The compiler bakes `release_resource` into both paths at compile time.
There is no runtime coordination needed.

---

## Bare except (catch-all)

A bare `except:` catches any unmatched error:

```python
@flow
def resilient_pipeline(p: dict) -> dict:
    try:
        p = risky_operation(p)
    except ValueError:
        p = handle_known_error(p)
    except:
        p = handle_unknown_error(p)
    return p
```

The catch-all is implemented via `policies.default.thenRoute` — when no
rule matches, the default policy routes to the bare-except router.

---

## raise in except body

`raise` inside an `except` block terminates the flow. The except_router
routes to an empty path, which sends the envelope to `x-sink` with the
error preserved:

```python
@flow
def strict_pipeline(p: dict) -> dict:
    try:
        p = handler(p)
    except ValueError:
        p = log_error(p)
        raise
    return p
```

On `ValueError`: `log_error` runs, then the envelope goes to `x-sink`
with `status.phase=failed`. The `return p` line is never reached.

---

## Combining with other flow constructs

### try/except with if/else

```python
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
```

All actors inside the `try` body — `charge_card`, `process_bank_transfer`,
and `record_transaction` — get the same resiliency rules. On error from
any of them:

```
except_router
  SET route.next = [seq_router, audit_log, send_receipt]
      │
      ▼
  p["status"] = "payment_failed"
  notify_payment_failure → audit_log → send_receipt → x-sink
```

The if/else router and `record_transaction` are skipped because the
except_router **overwrites** `route.next` (SET, not prepend).

### try/except with while loops

```python
@flow
def retry_pipeline(p: dict) -> dict:
    p["attempt"] = 0
    while p["attempt"] < 3:
        p["attempt"] += 1
        try:
            p = call_external_api(p)
        except ConnectionError:
            p = log_retry(p)
    return p
```

On each iteration, if `call_external_api` throws `ConnectionError`, the
except_router routes to `log_retry`, then back to the while loop router
for the next iteration. This gives you application-level retry with
custom recovery logic between attempts.

---

## What you cannot do

| Pattern | Supported? | Alternative |
|---------|-----------|-------------|
| `except ValueError as e:` | No | Error details are in `status.error` (read via ABI) |
| `try: ... else:` | No | Use a separate `if` after the try block |
| `try: ... finally:` (no except) | No | Use a context manager (`with`) |
| `raise` outside except | No | Use resiliency rules in `.asya/config.yaml` |
| Nested try/except | Yes | Each level gets its own rules |
| try/except wrapping fan-out | Yes | All fan-out actors get the rules |

---

## How the compiler transforms try/except

For readers who want to understand what the compiler generates:

```
Source:                           Compiled:
                                  ┌─────────────┐
try:                              │ start_       │
    p = actor_a(p)    ──────────► │ prepend      │
    p = actor_b(p)                │ [a, b, c]    │  ← success path
except ValueError:                └──────────────┘
    p = handler(p)
p = continuation(p)              ┌──────────────────┐
                                  │ except_router     │
                                  │ SET route.next =  │
                                  │ [handler, c]      │  ← error path
                                  └──────────────────┘

                                  actor_a manifest:
                                    resiliency.rules:
                                      - errors: [ValueError]
                                        policy: try_except_line_N_0

                                  actor_b manifest:
                                    (same rules as actor_a)
```

The except_router uses **SET** (overwrite) instead of prepend, which
replaces the entire remaining route. This skips any actors between the
failing actor and the end of the try body.

---

## See also

- [Examples](../../examples/flows/) — teaser flow examples; comprehensive `try_except_*.py` patterns in [examples/end-to-end/monorepo/resiliency](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo/src/resiliency/flows)
- [Actor Timeouts](guide-timeouts.md) — per-actor execution deadlines
- [Pause/Resume](guide-pause-resume.md) — human-in-the-loop error recovery

**Platform configuration**: To configure retry policies, error routing rules,
and resiliency settings at the infrastructure level, see
[setup/guide-error-handling.md](../setup/guide-error-handling.md).
