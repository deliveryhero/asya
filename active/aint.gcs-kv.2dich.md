---
title: Go GCS-backed state proxy (gcs-kv) with DuckDB /query — mirrors s3kv
status: open
priority: 2 # medium
---

Add gcskv Go connector: GCS CRUD (native generation-based CAS) + shared DuckDB /query engine from s3kv. Wire into gateway chart as backend: gcskv, switch pubsub-gcs E2E to gcskv.
