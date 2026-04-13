---
title: "Transport: add SendWithDelay() and rename Nack() to Requeue()"
status: merged
priority: 1
---

Extend the transport interface in src/asya-sidecar/pkg/transport/transport.go.

Changes:
1. Add SendWithDelay(ctx, queueName, body, delay time.Duration) error
2. Rename Nack() to Requeue() -- semantics: 'best-effort optimization before crashing'
3. Implement SendWithDelay for SQS transport (DelaySeconds parameter on SendMessage)
4. Implement SendWithDelay for RabbitMQ transport (x-delayed-message plugin or TTL+DLX)
5. Update all Nack() call sites to Requeue()
6. Add ErrDelayNotSupported error for transports without native delay

SQS note: DelaySeconds max is 900s (15 min). For longer delays, chain multiple sends.
RabbitMQ note: requires x-delayed-message plugin or TTL+dead-letter-exchange pattern.

Unit tests: test SendWithDelay for each transport, test Requeue behavior, test ErrDelayNotSupported.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Transport Interface Changes section)


---
_Migrated from beads `asya-7xqz`_
