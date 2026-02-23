---
title: "Flow compiler: emit prev/curr/next route format"
priority: 2 # medium
type: task
dependencies:
  - 1iah/1iqkcq
---

Update flow DSL code generator to emit routers using {prev, curr, next} route format instead of {actors, current}. Update resolve() functions in generated routers.py. Update all flow test fixtures in src/asya-testing/.
