---
title: "Gateway: POST /a2a/tasks/{id}:pause external pause endpoint"
priority: 2 # medium
type: task
dependencies: [1ixy/1kmp6r]
---

Add external pause endpoint. Mark task as paused (no pause metadata since user-initiated). SSE notification. Add POST /a2a/tasks/{id}:pause REST endpoint and tasks/pause JSON-RPC method. Unit tests.
