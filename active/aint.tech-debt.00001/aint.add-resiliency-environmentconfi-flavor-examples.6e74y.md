---
title: Add resiliency EnvironmentConfig flavor examples
status: open
priority: 2
---

## Context

The error-handling RFC proposed EnvironmentConfig flavors for reusable resiliency profiles (e.g. `retry-3x-exponential`). The mechanism exists in Crossplane but no example EnvironmentConfigs with resiliency config ship with the project. None of the example AsyncActor manifests in `examples/asyas/` use the `resiliency` block either.

## Problem

Users have no reference for:
1. How to define reusable resiliency profiles as EnvironmentConfig flavors
2. How to apply them to actors via `compositionSelector`
3. Common resiliency presets for typical workloads

## Deliverables

1. Example EnvironmentConfigs in `examples/` or `deploy/`:
   - `retry-aggressive` — 5 attempts, 500ms initial, exponential, for idempotent fast APIs
   - `retry-conservative` — 3 attempts, 5s initial, exponential, for expensive LLM calls
   - `retry-none` — maxAttempts=0, for fire-and-forget actors
   - `ai-workload` — 5 attempts, 2s initial, nonRetryableErrors=[TokenLimitExceeded, InvalidPrompt], actorTimeout=120s

2. Example AsyncActor manifests that reference resiliency config (update existing examples)

3. Documentation in quickstart or resiliency section showing the pattern

## References

- Error handling RFC section "Reusability via EnvironmentConfig (Flavors)"
- Related aint `1f8j` — Document example overlay EnvironmentConfigs for asya-quickstart
