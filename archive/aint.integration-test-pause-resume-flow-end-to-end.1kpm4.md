---
title: "Integration test: pause/resume flow end-to-end"
status: merged
priority: 2 # medium
tags:
  - pr:225
dependencies:
  - 1kk00
  - 1knc9
  - 1knff
  - 1ka9i
  - 1k2y7
---


Integration test in testing/integration/ that validates the full pause/resume flow: message enters pipeline, hits x-pause, gateway receives paused status, client sends resume input, x-resume loads and merges, pipeline continues. Test actor-initiated and external pause. Test cancel. Test timeout freeze/thaw across pause.
