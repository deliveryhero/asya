---
title: "Gateway: accept paused phase and store pause metadata"
priority: 2 # medium
tags:
  - pr:217
dependencies:
  - 1ixy/1kwi46
  - 1ixy/1kx4xg
---


Update gateway progress handler to accept phase=paused from sidecar. Extract pause metadata from progress update, store in pause_metadata JSONB column. Notify SSE subscribers with input_required A2A state. Unit tests.
