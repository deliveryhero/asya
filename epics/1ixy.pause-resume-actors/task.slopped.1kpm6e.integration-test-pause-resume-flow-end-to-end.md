---
title: "Integration test: pause/resume flow end-to-end"
priority: 2 # medium
type: task
---

Integration test in testing/integration/ that validates the full pause/resume flow: message enters pipeline, hits x-pause, gateway receives paused status, client sends resume input, x-resume loads and merges, pipeline continues. Test actor-initiated and external pause. Test cancel. Test timeout freeze/thaw across pause.
