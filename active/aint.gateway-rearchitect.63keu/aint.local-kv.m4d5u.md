---
title: "PR6: local-kv — low-infra gateway state proxy (in-memory + PVC, DuckDB /query)"
status: open
priority: 2 # medium
---

New state proxy binary for gateway mesh state: in-memory (mode=inmem, replicas=1) or file-based on PVC (mode=pvc, replicas=1). DuckDB reads local files directly — no S3 GETs for FindExpired. Active/archive schema as config option. sqs-s3-pvc E2E profile removes Postgres dependency.
