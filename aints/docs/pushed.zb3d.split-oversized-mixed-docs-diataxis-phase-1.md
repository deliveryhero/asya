---
title: Split oversized mixed docs (Diataxis Phase 1)
priority: 2 # medium
tags:
  - pr:338
dependencies:
  - u1zh
---


Reorganize existing docs by splitting files that mix Diataxis quadrants. No new content — just move and restructure.

Tasks:
1. Split `reference/flow-dsl.md` (990 lines) → keep reference + new `explanation/flow-compilation.md`
2. Split `tutorials/agentic-patterns.md` (660 lines) → keep tutorial + new `explanation/agentic-design.md` + new `reference/agentic-cheatsheet.md`
3. Split `features/resiliency.md` → keep reference + new `howto/configure-retries.md`
4. Split `features/task-pause.md` → keep explanation + new `howto/setup-pause-resume.md`
5. Move `architecture/asya-lab.md` → `reference/cli.md` (expand)
6. Consolidate `architecture/autoscaling.md` + `operate/scaling.md` → `howto/configure-autoscaling.md`

See parent aint u1zh for full audit context.
