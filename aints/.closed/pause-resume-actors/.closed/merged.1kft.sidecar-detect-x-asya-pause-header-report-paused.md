---
title: "Sidecar: detect x-asya-pause header and report paused phase"
priority: 2 # medium
tags:
  - pr:217
dependencies:
  - 1ixy/1kitzu
---


In router.go handleSuccessResponse, check for x-asya-pause header in runtime response. When present: parse JSON value, report phase=paused to gateway via POST /tasks/{id}/progress with pause metadata, ack message, do NOT route to next actor. Unit tests for header detection and pause reporting.
