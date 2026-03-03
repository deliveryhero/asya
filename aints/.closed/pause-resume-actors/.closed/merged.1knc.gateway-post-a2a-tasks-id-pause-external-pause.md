---
title: "Gateway: POST /a2a/tasks/{id}:pause external pause endpoint"
priority: 2 # medium
tags:
  - pr:217
dependencies:
  - 1kmp
---


Add external pause endpoint. Mark task as paused (no pause metadata since user-initiated). SSE notification. Add POST /a2a/tasks/{id}:pause REST endpoint and tasks/pause JSON-RPC method. Unit tests.
