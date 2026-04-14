---
title: "Compiler: prevent shared base/ dir when stamping manifests without project config"
status: open
priority: 2
---

The compile-flows pre-commit hook runs flows in parallel. Flows without .asya/config.yaml (e.g. examples/flows/) generate manifests into a shared compiled/base/ dir instead of per-flow dirs. This causes OSError: Directory not empty in CI. Root cause: _stamp_manifests falls back to the output_dir when no project exists, and the ManifestTemplater creates base/ relative to it. Fix: skip manifest stamping entirely when no project config exists, or resolve the output path per-flow.
