# Design Principle 001: FS-Like State Proxy Interface

**Status:** Accepted
**Date:** 2026-04-14

## Principle

Every state proxy MUST expose a filesystem-like interface. Actor and flow handler
code interacts with state exclusively through standard file I/O operations
(`open()`, `os.listdir()`, `os.stat()`, etc.) on mount paths.

## Rationale

This constraint enables two critical properties:

1. **Local testability without dependencies.** A handler function that reads
   `/datasets/train/metadata.json` and writes `/metrics/epoch-001.json` is testable
   on a developer's laptop by simply creating those files on the real filesystem.
   No SDK imports, no mock clients, no running infrastructure.

2. **Zero lock-in.** Actor code has no awareness of the storage backend (S3, Redis,
   GCS, PVC, git). Swapping backends is a manifest change, not a code change.

## Rules

- Actor handlers MUST NOT import storage SDKs (boto3, redis-py, gcsfs, etc.)
  for state managed by state proxies.
- New state proxy types MUST translate their domain operations into file I/O
  semantics (read, write, list, stat, delete).
- If a domain does not map naturally to file I/O (e.g., LLM inference,
  streaming RPCs), it is NOT a state proxy — use a different sidecar pattern
  or direct SDK calls in the handler.
- The sidecar is the only component that holds backend credentials and SDK
  dependencies.

## Implications for New State Proxies

When designing a new state proxy, the litmus test is:

> Can a developer test this handler by creating plain files in a temp directory?

If yes — it's a state proxy. If no — it belongs in a different abstraction.

## Examples

| Domain | FS mapping | State proxy? |
|---|---|---|
| Datasets (S3) | `open("/datasets/v1/img001.jpg")` | Yes |
| Experiment tracking (git-aint) | `open("/aint/active/aint.train.abc.md", "w")` | Yes |
| Actor memory | `open("/memory/project.pipeline.md")` | Yes |
| Metrics (TFEvents) | `tf.summary.create_file_writer("/metrics/run-1/")` | Yes |
| LLM inference | request/response, not read/write | No |
