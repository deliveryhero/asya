---
title: "PR3: Sidecar changes (envelope gateway URL + unified events + pre-flight)"
status: open
priority: 1
dependencies: [9bb3j]
tags: [gateway-rearchitect]
---

Update asya-sidecar to work with new mesh-api: read gateway URL from envelope
header, unified event POST, pre-flight cancel/pause check. ~200 LOC changes
in src/asya-sidecar/ (different Go module from mesh-api).

Depends on: PR1 (mesh-api core must exist for testing).
Can be parallelized with PR2 (protocol adapters).

See plan.md for detailed execution plan.
