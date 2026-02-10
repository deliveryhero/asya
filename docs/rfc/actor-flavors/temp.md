# ADR: Per-Error-Type Retry Counts (Future Extension)

**Status**: Deferred (noted during error handling RFC brainstorm)

**Context**: When designing `ASYA_ERROR_MAX_RETRY`, we considered whether the retry counter should be global (single counter for all error types) or per-error-type.

**Decision**: Start with global counter (`ASYA_ERROR_MAX_RETRY=5` means 5 total attempts regardless of error type).

**Reasoning**:
- If a message fails 5 times with *different* error types each time (e.g., `ValueError` then `FileNotFoundError` then `ValueError`), it's likely fundamentally broken, not just unlucky
- Per-error-type counting adds complexity to message metadata (need a `map[error_type]int` instead of a single integer)
- The global counter covers >95% of real-world retry scenarios (transient failures of the same kind)
- Asya's goal is to make in-handler retry libraries (like tenacity) unnecessary for most use-cases

**Future Extension**: If needed, support per-error-type overrides:
```
ASYA_ERROR_MAX_RETRY=5                    # default for all errors
ASYA_ERROR_MAX_RETRY__ValueError=2        # override: only 2 retries for ValueError
ASYA_ERROR_MAX_RETRY__TimeoutError=10     # override: more retries for timeouts
```

The double-underscore separator (`__`) distinguishes the error-type suffix from the config key prefix (`ASYA_ERROR_`).

**Related**: Actor flavors (future) could set namespace-level defaults for `ASYA_ERROR_FATAL_ERRORS` and `ASYA_ERROR_MAX_RETRY`, reducing per-actor configuration burden.


 ┌────────────┬─────────────────────────────────────────────────────────────┬──────────────────────────────────────────┐
  │ Dimension  │                      What it controls                       │             Example flavors              │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ compute    │ CPU, memory, GPU, nodeSelector, tolerations                 │ cpu-small, gpu-a100, memory-64gi, <custom> │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ scaling    │ min/max replicas, cooldown, polling, queue length target    │ scale-to-zero, always-on, burst-100      │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ queue      │ visibility timeout, retention, DLQ config, long-polling     │ fast-ack, long-running, durable-7d       │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ sidecar    │ sidecar image/tag, sidecar resources, extra sidecar env     │ sidecar-slim, sidecar-debug              │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ scheduling │ affinity, anti-affinity, topology spread, priority class    │ spread-zones, colocate, preemptible      │
  ├────────────┼─────────────────────────────────────────────────────────────┼──────────────────────────────────────────┤
  │ security   │ IRSA role, service account, pod security context, runAsUser │ irsa-readonly, irsa-s3-write, restricted │
  └────────────┴─────────────────────────────────────────────────────────────┴──────────────────────────────────────────┘
  App dimensions (developer domain)
  ┌───────────────┬──────────────────────────────────────────────────────────────┬───────────────────────────────────────────┐
  │   Dimension   │                       What it controls                       │              Example flavors              │
  ├───────────────┼──────────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
  │ retry         │ retry count, backoff strategy, error routing                 │ no-retry, retry-3x-exp, retry-forever     │
  ├───────────────┼──────────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
  │ runtime       │ Python executable, handler mode, validation, PYTHONPATH      │ conda, payload-mode, envelope-mode        │
  ├───────────────┼──────────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
  │ observability │ log level, tracing config, metrics labels                    │ debug-verbose, prod-quiet, traced         │
  ├───────────────┼──────────────────────────────────────────────────────────────┼───────────────────────────────────────────┤
  │ lifecycle     │ graceful shutdown timeout, startup/readiness probes, preStop │ fast-start, slow-model-load, graceful-60s │


  ★ Insight ─────────────────────────────────────
  The DDD observation is spot-on. The current XRD is structured by K8s resource topology (workload → template → containers → resources). Flavors restructure it by business concern (compute,
   scaling, retry). This is only valuable if: (1) the same concern appears across many actors, and (2) different personas care about different concerns. If every actor is unique, flavors
  just add indirection.




 Message Status Through the Retry Flow

  To answer your question — here's the status progression:

  1. Message created by gateway/first actor:
     status: {phase: "pending", created_at: "...", updated_at: "..."}

  2. Sidecar receives, before calling runtime:
     status: {phase: "processing", actor: "actor-b", attempt: 1, max_attempts: 5, ...}

  3. Runtime returns error, sidecar decides to retry:
     status: {phase: "retrying", actor: "actor-b", attempt: 1, max_attempts: 5,
              error: {type: "TimeoutError", mro: ["Exception"], message: "..."}, ...}
     → SendWithDelay(own queue, this message, delay)

  4. Message reappears after delay, sidecar receives again:
     status: {phase: "processing", actor: "actor-b", attempt: 2, max_attempts: 5, ...}
     (error cleared — fresh attempt)

  5a. Runtime succeeds → sidecar routes to next actor:
     status: {phase: "processing", actor: "actor-c", attempt: 1, max_attempts: 5, ...}
     (attempt reset for new actor)

  5b. Runtime fails again, max attempts reached:
     status: {phase: "failed", reason: "MaxRetriesExhausted", actor: "actor-b",
              attempt: 5, max_attempts: 5,
              error: {type: "TimeoutError", mro: ["Exception"], message: "..."}, ...}
     → send to _sink

  Key transitions:
  - pending → processing (sidecar receives)
  - processing → retrying (error, will retry)
  - retrying → processing (redelivered after delay)
  - processing → succeeded (terminal)
  - processing → failed / retrying → failed (terminal)
