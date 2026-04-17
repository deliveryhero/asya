---
title: "PR1: PG state-proxy connector + asya-mesh-api core"
status: merged
priority: 1 # high
tags:
  - gateway-rearchitect
---


PG state-proxy connector (Go, KV + /query) and asya-mesh-api core binary
(/api/v1/mesh/). Single PR — the connector has no standalone value without
mesh-api, and testing them separately means mocking the connector.

~1,500-2,000 LOC Go combined. No dependencies on other PRs.

See plan.md for detailed execution plan.
