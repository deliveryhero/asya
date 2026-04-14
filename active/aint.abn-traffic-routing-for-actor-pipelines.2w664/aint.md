---
title: A/B/N Traffic Routing for Actor Pipelines
status: open
priority: 2
---

This epic introduces a two-layer mechanism for A/B/N testing, canary routing, and traffic splitting in Asya actor pipelines. Layer 1 adds a minimal header-based route override to the sidecar (static name remapping via dictionary lookup), while Layer 2 provides Python-level router actors for probabilistic and conditional routing logic. Together, these layers fill a gap in the cloud-native ecosystem where no existing tool supports progressive delivery on message queues.
