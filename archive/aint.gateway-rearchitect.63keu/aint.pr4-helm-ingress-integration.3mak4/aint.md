---
title: "PR4: Helm chart + Ingress + deployment integration + docs"
status: merged
priority: 1 # high
tags:
  - gateway-rearchitect
dependencies:
  - cjrxo
  - iq8gi
---


Helm chart for asya-gateway deployment (mesh-api + adapters + state-proxies),
nginx Ingress config (external + internal, consistent hash), Crossplane
composition update (remove ASYA_GATEWAY_URL), E2E tests, documentation.

Depends on: PR2 (adapters) + PR3 (sidecar). Final integration PR.

See plan.md for detailed execution plan.
