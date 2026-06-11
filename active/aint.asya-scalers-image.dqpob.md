---
title: Publish scaler as standalone asya-scalers image; fix release/CI/dependabot image wiring
status: pushed
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/dqpob.asya-scalers-image
  - branch:dqpob.asya-scalers-image
---



Now that ghcr.io/deliveryhero/asya-scalers and asya-state-proxy-{go,py} are public, remove the publish-readiness shims:

1. Move KEDA external scaler from src/asya-crew/cmd/scaler-pubsub into a standalone src/asya-scalers component + real image (was a placeholder alpine echo image).
2. Remove scaler-builder stage from asya-crew Dockerfile.
3. Wire src/asya-scalers into Makefile (setup/test-unit/build-go/clean/cov) and ci.yml unit-tests matrix (scaler was tested nowhere).
4. Point crossplane chart pubsub.keda.scaler.image.repository at asya-scalers (was temporarily asya-crew).
5. release.yml: add asya-state-proxy-go/py to the tag-latest loop + release summary (built+pushed but never tagged latest nor advertised).
6. dependabot.yml: update gomod dir to /src/asya-scalers.
7. docs/reference/scalers/pubsub.md: reflect standalone image.
