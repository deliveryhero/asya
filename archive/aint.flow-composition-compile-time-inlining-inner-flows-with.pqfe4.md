---
title: "Flow composition: compile-time inlining of inner flows with visual grouping"
status: rejected
priority: 2
dependencies:
  - o8qlz
---

When a @flow calls another @flow, compiler inlines the inner flow body at compile time. All actors get outer flow asya.sh/flow label. Inner flow actors appear in a group in graph.json for visual clustering. No additional K8s labels for inner flows. Multiple nesting levels produce nested groups. Each reference to same inner flow creates new actor instances (not shared). See RFC section: Flow composition (inline expansion).
