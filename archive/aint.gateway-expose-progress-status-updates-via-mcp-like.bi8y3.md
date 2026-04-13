---
title: "Gateway: expose progress/status updates via MCP (like A2A blocking wait)"
status: rejected
priority: 1
parent: ezpsa
---

Won't do - not a bug.

A2A message/send blocks until completion, relaying progress via waitAndRelayEvents (PR #368). MCP tools/call returns immediately with task_id — no blocking wait, no progress relay. Need: MCP Streamable HTTP tools/call should block and relay progress events (or provide equivalent mechanism). Reference: PR #368 (A2A blocking wait implementation).
