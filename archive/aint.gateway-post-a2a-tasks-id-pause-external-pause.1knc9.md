---
title: "Gateway: POST /a2a/tasks/{id}:pause external pause endpoint"
status: merged
priority: 2
parent: hwek2
dependencies:
  - 1kmp
tags:
  - pr:217
---

Add external pause endpoint. Mark task as paused (no pause metadata since user-initiated). SSE notification. Add POST /a2a/tasks/{id}:pause REST endpoint and tasks/pause JSON-RPC method. Unit tests.
