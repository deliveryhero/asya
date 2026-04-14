---
title: "Gateway: listen on _sink queue and support status.phase for result reporting"
status: merged
priority: 2
dependencies:
  - 1ffmx
tags:
  - pr:193
---

Update asya-gateway's ResultConsumer to support the new _sink queue and status-based result reporting.

Changes:
1. ResultConsumer: add _sink queue to listener (alongside happy-end/error-end for backward compat)
2. Parse status.phase from message to determine succeeded/failed (instead of relying on queue name)
3. Parse status.reason, status.error for enriched failure reporting
4. Update /tasks/{id}/final endpoint to accept richer status payload
5. Store attempt count and error details in task record

Migration: listen on all three queues (_sink, happy-end, error-end) during transition period. Remove happy-end/error-end listeners after full migration.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Migration Path section)


_Migrated from beads `asya-9lhh`_
