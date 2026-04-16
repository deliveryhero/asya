---
title: Handle MQ redelivery duplicate message processing
status: open
priority: 3 # low
---

When MQ times out and redelivers, two pods process the same message. Monotonic status ordering prevents regression but duplicate work wastes resources. Fix: idempotency key or distributed lock. Related: gateway-rearchitect/63keu.
