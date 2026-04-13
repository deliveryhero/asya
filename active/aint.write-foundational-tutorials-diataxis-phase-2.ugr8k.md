---
title: Write foundational tutorials (Diataxis Phase 2)
status: pushed
priority: 2
dependencies:
  - zb3d
tags:
  - pr:338
---

Fill the biggest Diataxis gap: learning-oriented tutorials that teach by doing.

Tutorials to write:
1. `tutorials/first-actor.md` — Build your first actor (echo actor, deploy to Kind, send message, see result)
2. `tutorials/first-pipeline.md` — Chain two actors, observe envelope routing
3. `tutorials/first-flow.md` — Write a Python Flow DSL file, compile, deploy
4. `tutorials/pause-resume.md` — Add human-in-the-loop to a pipeline

Each tutorial must:
- Have a clear learning goal stated up front
- Guide the reader through concrete steps with verifiable outcomes
- NOT include reference tables or architectural rationale (link to those instead)
- Be testable end-to-end on a local Kind cluster

See parent aint u1zh for full audit context.
