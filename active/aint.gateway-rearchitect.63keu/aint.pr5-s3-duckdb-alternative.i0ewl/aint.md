---
title: "PR5: S3 state-proxy with DuckDB query (high-latency alternative)"
status: open
priority: 2
dependencies: [9bb3j]
tags: [gateway-rearchitect]
---

S3 state-proxy connector with DuckDB for /query support. Alternative to PG
for deployments that don't want PostgreSQL. ~400-600 LOC Go.

Independent of PR2-PR4. Depends on PR1 for interface compatibility.

See plan.md for detailed execution plan.
