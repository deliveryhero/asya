---
title: "Flow/Actor DSL: tenacity.retry decorator detection and ASYA_ERROR_* config generation"
priority: 3 # low
type: task
tags:
  - type:feature
---




Extend Flow DSL compiler (and potentially Actor DSL) to detect tenacity.retry() decorators on actor handler functions. When detected: (1) strip the decorator for Asya-managed retry (handler runs pure), (2) extract retry config (max attempts, backoff strategy, jitter) from decorator arguments, (3) generate corresponding ASYA_ERROR_* env vars for the AsyncActor CRD. This provides familiar Python syntax for retry configuration while keeping the actual retry at infrastructure level via the error-handler crew actor.


---
_Migrated from beads `asya-pe6n`_
