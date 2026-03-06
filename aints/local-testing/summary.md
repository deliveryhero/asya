---
title: Local testing workflow in docker-compose
priority: 2 # medium
---


Ideas:
- use existing XRD + handlers code, generate docker compose, run runtime containers, maybe even run sidecar containers for routing (similar to integration tests setup)
- use deployed version of the flow + run local actor as a pure python function intercepting calls to a real actor - similar to a/b testing but for local debugging only)
