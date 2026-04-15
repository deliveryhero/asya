# Design Principle 002: State Proxy for State, Not Data

**Status:** Accepted
**Date:** 2026-04-15

## Principle

State proxy is designed for **state** (infrequent, small-to-medium I/O) — not
for **bulk data** (frequent, latency-critical I/O like training datasets).

## Rationale

State proxy translates every `open()` call to an HTTP request over Unix socket
to a sidecar, which translates to a storage backend call (S3 GET/PUT). This
adds ~50ms latency per operation. For infrequent operations (write a checkpoint,
read a config file, update experiment status), this is fine. For training loops
iterating over thousands of images per epoch, it's unacceptable.

## Rules

- **Use state proxy for**: experiment tracking, memory, metrics (TFEvents),
  checkpoints (infrequent write/read), small metadata files, labels
- **Use PVC or emptyDir for**: training datasets, large file collections read
  in tight loops, anything accessed by PyTorch DataLoader or similar
- **Pattern for bulk data**: init container or startup script does
  `aws s3 sync` (or `gsutil rsync`) to copy data from S3 to local volume
  (PVC or emptyDir) before training starts. Training reads local files at
  native filesystem speed.
- **For the workbench**: S3 Mountpoint CSI is acceptable for browsing/exploration
  (human-speed I/O), but not for automated training loops

## Implications

When designing new state proxies, consider the access pattern:

| Access pattern | Right tool |
|---|---|
| Read once, write once, <100 ops/min | State proxy |
| Read 1000s of files per iteration | PVC / emptyDir + bulk copy |
| Append-only log file | State proxy (with append mode) |
| Random access within large files | PVC (state proxy can't seek) |
