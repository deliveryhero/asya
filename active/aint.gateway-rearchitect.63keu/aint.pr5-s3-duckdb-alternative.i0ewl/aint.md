---
title: "PR5: S3 state-proxy with DuckDB query (high-latency alternative)"
status: working
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - gateway-rearchitect
dependencies:
  - 9bb3j
---


S3 state-proxy connector with DuckDB for /query support. Alternative to PG
for deployments that don't want PostgreSQL. ~400-600 LOC Go.

Independent of PR2-PR4. Depends on PR1 for interface compatibility.

See plan.md for detailed execution plan.
