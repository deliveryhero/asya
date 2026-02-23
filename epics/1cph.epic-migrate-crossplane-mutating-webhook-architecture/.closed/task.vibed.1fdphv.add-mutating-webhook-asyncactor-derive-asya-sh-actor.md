---
title: Add mutating webhook for AsyncActor to derive asya.sh/actor label from spec.actor
priority: 2 # medium
type: task
tags:
  - type:feature
  - worktree:1cph/1fdphv.add-mutating-webhook-asyncactor-derive-asya-sh-actor
  - pr:188
---








Extend asya-injector with a second webhook entry that intercepts AsyncActor claim CREATE/UPDATE operations and copies spec.actor value to metadata.labels["asya.sh/actor"]. This ensures the label is always present and consistent with the spec field, enabling kubectl label queries without requiring users to set both.

Implementation:
- New handler /mutate-asyncactor in asya-injector (~40 lines Go)
- New route registration in main.go
- New webhook entry in MutatingWebhookConfiguration targeting asyncactors.asya.sh on CREATE+UPDATE
- Unit tests following existing handler_test.go patterns

Depends on: spec.actor field being added to XRD (asya-v2hs)


---
_Migrated from beads `asya-6nva`_
