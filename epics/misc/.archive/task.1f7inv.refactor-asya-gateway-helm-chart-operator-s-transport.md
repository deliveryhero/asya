---
title: "Refactor asya-gateway Helm chart to operator's transport pattern"
status: done
priority: 2 # medium
type: task
---



Refactor asya-gateway Helm chart to match operator's transport configuration pattern.

**Current State (Flat Structure)**:
- config.rabbitmqURL: "amqp://guest:guest@rabbitmq:5672/"
- config.rabbitmqExchange: "asya"
- config.sqsEndpoint: ""
- config.sqsRegion: ""
- Problem: Users must know to leave rabbitmqURL empty to use SQS

**Desired State (Nested Structure)**:
- transports.rabbitmq.enabled: false
- transports.rabbitmq.config.url, exchange, poolSize
- transports.sqs.enabled: false
- transports.sqs.config.endpoint, region, visibilityTimeout, waitTimeSeconds

**Gateway Transport Behavior (from research)**:
- Does NOT fail if both SQS and RabbitMQ are set
- SQS takes precedence over RabbitMQ (line 79 of gateway code)
- Defaults to SQS if neither is configured
- No explicit validation enforces 'exactly one transport'
- Solution: Helm configuration should prevent misconfiguration

**Files to Modify**:
1. deploy/helm-charts/asya-gateway/values.yaml - Replace flat config with nested transports
2. deploy/helm-charts/asya-gateway/templates/deployment.yaml - Update env var conditionals
3. deploy/helm-charts/asya-gateway/README.md - Document new structure
4. testing/e2e/profiles/rabbitmq-minio.yaml - Update test config
5. testing/e2e/profiles/sqs-s3.yaml - Update test config
6. testing/e2e/charts/values.yaml - Update defaults
7. testing/integration/gateway-actors/profiles/rabbitmq-minio.yml - Update docker compose
8. testing/integration/gateway-actors/profiles/sqs-s3.yml - Update docker compose

**Acceptance Criteria**:
- Helm chart lints without errors
- Templates render with transport-specific vars only (RabbitMQ: no SQS vars, vice versa)
- E2E tests pass: make test PROFILE=rabbitmq-minio && make test PROFILE=sqs-s3
- README updated with examples and alignment constraints


---
**Close reason**: Implemented gateway Helm chart refactor to use operator's nested transport pattern. Created PR and merged to main.


---
_Migrated from beads `asya-caq`_
