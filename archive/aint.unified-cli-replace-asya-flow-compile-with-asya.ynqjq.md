---
title: "Unified CLI: replace 'asya flow compile' with 'asya compile' top-level command"
status: rejected
priority: 2
dependencies:
  - o8qlz
---

Replace asya flow compile with asya compile as top-level command. File paths as arguments (tab-completable). Flow name inferred from @flow def name (kebab-case), override with --flow. Produces everything: routers.py + manifests + graph.json + DOT + MMD + SVG. --no-plot skips SVG/DOT/MMD but graph.json always produced. --python to override interpreter. --dry-run for preview. Prints flow name with export ASYA_LAB_FLOW=name hint. See RFC section: CLI interface.
