---
title: Rename flavor to overlay
status: merged
priority: 2
---

Rename the "flavor" concept (composable configuration presets for AsyncActors) to
"overlay" across the entire codebase. This frees "flavor" for a new user-facing
concept: pre-built Docker images that simplify the data scientist workflow.

The rename is purely cosmetic — no behavioral changes to the merge pipeline,
strategic merge patch logic, or Crossplane composition architecture. All external
references (XRD field names, Helm values, labels, Go module path, OCI image name)
change from `flavor` to `overlay`.

See `rfc.md` for the full inventory of changes and migration plan.
