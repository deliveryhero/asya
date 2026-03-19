---
title: Remove /mesh/expose — ConfigMap+hot-reload is the only tool registration mechanism
priority: 2 # medium
---

The gateway has a /mesh/expose POST endpoint that lets actors register themselves dynamically at runtime. This was an earlier design that should be removed.\n\nInstead, use ONLY ConfigMap-based tool registration with hot-reload:\n- Tools defined in flows.yaml (mounted as ConfigMap)\n- Gateway watches and reloads every 10s (toolstore.Watch)\n- Optionally expose /mesh/config-reload to trigger immediate reload\n\nReason: security/RBAC simplicity — actors should not have network-level write access to gateway registry.
