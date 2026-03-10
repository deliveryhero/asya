---
title: "Simplify component/integration tests: unix socket transport + local FS storage"
priority: 3 # low
---

Rework all component and integration tests that do not test specific transport/storage backends to use unix socket transport (ASYA_TRANSPORT=socket) and local filesystem as storage (shared Docker volume, no MinIO/SQS/RabbitMQ needed).

## Motivation

Current component/integration tests parametrize over transport (rabbitmq/sqs/pubsub) and storage (minio/s3/gcs), but most tests validate routing, error handling, SLA, retry — behaviors that are transport-agnostic. This forces every test run to boot heavy infrastructure (RabbitMQ, LocalStack) that has nothing to do with what is being tested.

The socket transport (see aint cavw) replaces message queues with Unix domain sockets on a shared Docker volume. For storage, avoid interception entirely: when ASYA_STATE_PROXY_MOUNTS is not set, the runtime writes to the local container filesystem. A shared Docker volume at /state/ is sufficient for local testing.

## Goal

- Each test suite gets a single docker-compose.yml (no profiles/ directory)
- No RabbitMQ, SQS, LocalStack, or MinIO containers in component/integration tests
- Transport-specific and storage-specific behavior tested only in e2e (parametrized over real backends)

## Scope

- testing/integration/sidecar-runtime/ -- replace 3 transport profiles with single socket compose
- testing/integration/gateway-actors/ -- replace 3 profiles with socket + local FS volume
- testing/integration/fan-in/ -- replace 2 profiles with socket + local FS volume
- testing/integration/stateful-actors/ -- single socket compose
- testing/integration/pause-resume/ -- replace 2 profiles with socket + local FS volume
- testing/component/sidecar/ -- replace 2 transport profiles with single socket compose
- All conftest.py: replace transport_helper dispatch with SocketTestHelper
- Fix DRY violations (RabbitMQTestHelper/SQSTestHelper duplicated in test files and conftest.py) as part of cleanup

## Dependencies

- Depends on socket transport implementation (aint cavw)
- Depends on SocketTestHelper in asya-testing (inject/observe via actor socket files)
