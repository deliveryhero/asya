---
title: "Tier 2: Infrastructure (state proxies, code delivery)"
status: open
priority: 2 # medium
tags: [tier-2, autoresearch]
---

## Goal

Proper code delivery, crash-resilient writes, scheduled flows. Enables complex
training pipelines without manual kubectl for every code change.

## Sub-aints

- [jbtnm] Append mode state proxy
- [pr3ib] Periodic flush for buffered writes
- [cy0p1] Git state proxy (full read-write)
- [34yhs] Cron flow pattern + observability

**Moved to Tier 1**: [cynl0] XRD init/sidecar containers — blocks code delivery for experimentation
