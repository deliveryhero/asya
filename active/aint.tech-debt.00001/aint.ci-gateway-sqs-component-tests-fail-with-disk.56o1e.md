---
title: CI gateway (sqs) component tests fail with disk space exhaustion
status: open
priority: 3
parent: 00001
---

## Problem

Component tests for gateway (sqs) fail during Docker build with:

```
no space left on device
```

when writing `botocore/data/sso-admin/2020-07-20/service-2.json.gz`. The SQS
component tests build multiple Docker images (runtime, sidecar, etc.) and the
CI runner runs out of disk space before completing.

## Seen in

- PR #413 (run 24218853135, job 70705606617)

## Fix ideas

- Add `docker system prune` step before Docker builds in CI
- Use slimmer base images or multi-stage builds to reduce layer sizes
- Increase runner disk space or use a larger runner type
- Build images sequentially instead of in parallel to reduce peak disk usage
