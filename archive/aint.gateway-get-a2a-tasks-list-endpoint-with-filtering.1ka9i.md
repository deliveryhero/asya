---
title: "Gateway: GET /a2a/tasks list endpoint with filtering"
status: merged
priority: 3
parent: hwek2
dependencies:
  - 1kwi
  - 1kx4
tags:
  - pr:217
---

Add List method to TaskStore interface. Implement in PgStore with filtering (context_id, status, limit/offset pagination). Implement in in-memory Store. Add GET /a2a/tasks REST endpoint and tasks/list JSON-RPC method. Response includes tasks array, next_offset, total_count. Unit tests for filtering, pagination, empty results.
