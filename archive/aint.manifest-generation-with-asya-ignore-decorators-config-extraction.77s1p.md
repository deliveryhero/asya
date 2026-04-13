---
title: Manifest generation with ASYA_IGNORE_DECORATORS and config extraction
status: rejected
priority: 2
parent: pj0fo
dependencies:
  - o8ql
---

Compiler generates AsyncActor XR YAML manifests into kustomize base/ layer. Config extraction via treat-as:config rules: decorator args extracted to manifest fields, FQN added to ASYA_IGNORE_DECORATORS env var. Runtime strips decorators at load time. Handler source never modified. common/ overlay scaffolded once, never overwritten. Each actor gets manifest with handler ref, labels (asya.sh/flow, asya.sh/flow-role), extracted config. See RFC sections: Config extraction and decorator stripping, Separation of concerns.
