---
title: "Gateway: POST /a2a/tasks/{id}:cancel endpoint"
priority: 3 # low
type: task
tags:
  - pr:217
dependencies:
  - 1ixy/1kwi46
---


Add Cancel method to TaskStore interface. Implement in PgStore and in-memory Store. Validate task is not in terminal state (succeeded/failed/canceled). Mark as canceled, notify SSE subscribers. Add POST /a2a/tasks/{id}:cancel REST endpoint and tasks/cancel JSON-RPC method. Unit tests for state transition, terminal state rejection, SSE notification.
