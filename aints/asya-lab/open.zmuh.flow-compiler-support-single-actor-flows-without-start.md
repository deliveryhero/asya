---
title: "Flow compiler: support single-actor flows without start router"
priority: 2 # medium
---

Modify the flow compiler to not generate `start_<flow_name>` router for single-actor flows. A single-actor flow should compile to just the actor itself with `asya.sh/flow=<flow-name>` and `asya.sh/flow-role=entrypoint` labels, no router wrapper needed.

This simplifies the model: `asya flow expose` only accepts flows (not bare actors). If a DS wants to expose a single actor, they first declare it as a single-actor flow, which the compiler handles without generating unnecessary routers.

Context: design discussion on gateway tool exposure via ConfigMap. Restricting expose to flows-only means every exposed endpoint has a consistent label-based discovery model (`asya.sh/flow=...`).
