---
title: "Gateway: migrate progress tracking to prev/curr/next route"
priority: 2 # medium
type: task
dependencies:
  - 1iah/1ikdzb
---

Update gateway task types and progress tracking to use {prev, curr, next} route format. Update types.go Route struct, progress calculation in handlers.go (currently uses actors list + current index for percentage), and task store queries.
