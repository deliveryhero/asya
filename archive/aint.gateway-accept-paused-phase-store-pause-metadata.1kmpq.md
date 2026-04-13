---
title: "Gateway: accept paused phase and store pause metadata"
status: merged
priority: 2
dependencies:
  - 1kwi
  - 1kx4
tags:
  - pr:217
---

Update gateway progress handler to accept phase=paused from sidecar. Extract pause metadata from progress update, store in pause_metadata JSONB column. Notify SSE subscribers with input_required A2A state. Unit tests.
