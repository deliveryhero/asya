---
title: "Sidecar: detect x-asya-pause header and report paused phase"
status: merged
priority: 2
dependencies:
  - 1kit
tags:
  - pr:217
---

In router.go handleSuccessResponse, check for x-asya-pause header in runtime response. When present: parse JSON value, report phase=paused to gateway via POST /tasks/{id}/progress with pause metadata, ack message, do NOT route to next actor. Unit tests for header detection and pause reporting.
