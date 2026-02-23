---
title: Rename ASYA_HANDLER_MODE=envelope after handler signature redesign
priority: 3 # low
type: task
---



The ASYA_HANDLER_MODE=envelope value was intentionally preserved during the envelope→message/task rename (asya-830). It should be renamed after the handler signature is redesigned. This affects: asya_runtime.py mode constants, all handler mode validation code, test fixtures, docker-compose env vars, and documentation references. Coordinate with handler signature redesign work.


---
_Migrated from beads `asya-ob75`_
