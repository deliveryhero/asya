---
title: "Crew: create x-dlq standalone Go worker for infrastructure DLQ"
priority: 2 # medium
type: task
dependencies:
  - 1c46/1fezrw
---





Create a minimal standalone Go binary for processing transport-level DLQ messages.

Location: src/asya-crew/cmd/dlq-worker/ (Go binary, NOT a Python actor)

Behavior:
1. Poll DLQ queue using NATIVE transport SDK (not Asya transport abstraction)
2. Parse message to extract id field
3. POST failure status to gateway /tasks/{id}/final endpoint
4. Persist message directly to S3 (DO NOT forward to x-sink — avoids circular dependency)
5. ACK from DLQ

Design principle: different failure domain from sidecar. Uses native SDK (aws-sdk-go-v2 for SQS, amqp091-go for RabbitMQ) to avoid sharing bugs.

Config env vars:
- DLQ_QUEUE_URL: DLQ queue URL
- DLQ_TRANSPORT: sqs|rabbitmq
- GATEWAY_URL: x-gateway URL for status reporting
- S3_BUCKET: S3 bucket for message persistence
- S3_ENDPOINT: MinIO endpoint (optional)
- S3_PREFIX: Storage prefix (default: dlq/)

Deploy as K8s Deployment (own Helm chart or included in asya-crew chart), NOT as AsyncActor.

Start with SQS implementation, add RabbitMQ later.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (x-dlq Worker section)



---
**Close reason**: Implemented in PR #184: standalone Go DLQ worker with SQS support, S3 persistence, gateway reporting


---
_Migrated from beads `asya-gin6`_
