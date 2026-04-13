---
title: Deploy Tempo in monitoring namespace instead of user namespace
status: open
priority: 2
---

Modify helm charts so that Tempo is deployed in the monitoring namespace rather than in the user/actor namespace. Update namespace references in templates and any cross-namespace service references (e.g. sidecar OTLP endpoint configuration).
