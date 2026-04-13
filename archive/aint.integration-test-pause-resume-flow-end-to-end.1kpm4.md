---
title: "Integration test: pause/resume flow end-to-end"
status: merged
priority: 2
parent: hwek2
dependencies:
  - 1kk0
  - 1knc
  - 1knf
  - 1ka9
  - 1k2y
tags:
  - worktree:.worktrees/1ixy/1kpm6e.integration-test-pause-resume-flow-end-to-end
  - branch:1ixy/1kpm6e.integration-test-pause-resume-flow-end-to-end
  - pr:225
---

Integration test in testing/integration/ that validates the full pause/resume flow: message enters pipeline, hits x-pause, gateway receives paused status, client sends resume input, x-resume loads and merges, pipeline continues. Test actor-initiated and external pause. Test cancel. Test timeout freeze/thaw across pause.
