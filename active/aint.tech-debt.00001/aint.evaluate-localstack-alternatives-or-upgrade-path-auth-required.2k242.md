---
title: Evaluate LocalStack alternatives or upgrade path for auth-required versions
status: open
priority: 3
parent: 00001
---

LocalStack v2026.3.1+ requires LOCALSTACK_AUTH_TOKEN. We pinned to 4.4.0 as a stopgap. Options: (1) create a free LocalStack account and configure auth token in CI, (2) switch to ElasticMQ for SQS mocking, (3) monitor LocalStack free tier availability.
