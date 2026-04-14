---
title: GetTask history and artifacts from S3
status: merged
priority: 3
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/a2a-protocol-compliance-gateway/tgfp.gettask-history-artifacts-from-s3
  - branch:a2a-protocol-compliance-gateway/tgfp.gettask-history-artifacts-from-s3
  - pr:273
---

## Objective

Implement S3-backed history and artifact retrieval for GetTask, enabling full task history for paused and completed tasks.

## Scope

### 1. S3 fetch for GetTask

When `history_length > 0` or `include_artifacts: true`, fetch envelope payload from S3:

- **In-flight tasks**: `history` field omitted (not available from queues)
- **Paused tasks**: Fetch from S3 (persisted by x-pause), return last N messages from `payload.a2a.task.history`
- **Completed tasks**: Fetch from S3 (persisted by x-sink), return last N messages
- **S3 fetch failure**: `history` field omitted (field is optional per A2A spec)

### 2. Artifact retrieval

Same S3 fetch mechanism as history. When `include_artifacts=true`, read `payload.a2a.task.artifacts` from S3 result.

### 3. S3 client integration

Reuse existing S3/MinIO client configuration from x-sink/x-pause actors. Gateway needs read access to the result bucket.

## References

- RFC sections 7.3 (GetTask), 5.4 (History in Envelope Payload)
- RFC section 15.2 test matrix (GetTask paused with history)
- RFC section 15.3 integration tests (Pause/resume with S3)

## Acceptance Criteria

- GetTask returns history for paused tasks (fetched from S3)
- GetTask returns history for completed tasks (fetched from S3)
- GetTask omits history for in-flight tasks (spec-compliant)
- S3 fetch failure gracefully omits history (no error)
- Artifacts included when `include_artifacts=true`
- Integration tests with MinIO
