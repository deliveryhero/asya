---
title: "Gateway chart: projected volume for per-flow ConfigMaps (enable asya k apply without helm upgrade)"
status: merged
priority: 0 # critical
assignee: Artem Yushkovskiy
tags:
  - pr:386
---


The gateway chart mounts a single asya-gateway-flows ConfigMap. Per-flow CMs created by asya k apply are deployed but never read. Users must helm upgrade to register flows — unacceptable UX. Fix: change the volume to projected, add flowConfigMaps values field. Already prototyped in vppe branch (commit df2afbca).
