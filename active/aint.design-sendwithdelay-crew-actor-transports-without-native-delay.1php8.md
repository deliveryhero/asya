---
title: Design SendWithDelay crew actor for transports without native delay
status: open
priority: 2
tags:
  - type:feature
---

Design an asya-native way to implement SendWithDelay for transports that lack
native delayed delivery (Pub/Sub, RabbitMQ).

Proposed approach: a stateful crew actor (e.g. x-delay) that:
- Receives messages destined for delayed delivery
- Persists message bodies via state proxy
- Manages waiting times (when to re-send which message)
- min=max replicas = 1 (singleton)
- On restart/failure: reloads state into memory, resets timers based on
  persisted deadlines
- When timer fires: re-publishes message to the original target queue

This would replace ErrDelayNotSupported with a universal fallback mechanism
available to all transports.
