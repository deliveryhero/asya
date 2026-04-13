---
title: "Crew: two-layer termination with x-sink, x-sump, and configurable hooks"
status: merged
priority: 3
parent: s62ja
dependencies:
  - 1fsy
---

Redesign crew terminal actors with a two-layer termination scheme replacing happy-end and error-end.

## Architecture

**Layer 1 - x-sink** (role=sink): Reports final status to gateway, routes to configurable hooks.
**Layer 2 - x-sump** (role=sump): Final terminal. Emits Prometheus metrics, logs errors to stdout. Nothing below.

**Hooks**: Sequential chain of crew actors (e.g., checkpoint-s3, notify-slack) configured via ASYA_SINK_HOOKS env var. Each hook's sidecar points to x-sump as its sink. If a hook fails after retries, message goes to x-sump (logged, metrics emitted).

## Sidecar Config Changes (follow-up issue)

- ASYA_IS_END_ACTOR (bool) -> ASYA_ACTOR_ROLE (regular|sink|sump)
- ASYA_ACTOR_HAPPY_END + ASYA_ACTOR_ERROR_END -> ASYA_ACTOR_SINK

## Package Structure

src/asya-crew/asya_crew/
  sink.py                       - x-sink handler (validates status.phase, constructs hook route)
  sump.py                       - x-sump handler (logs errors, returns None)
  message_persistence/s3.py     - S3 message persistence (dual-purpose: hook or mid-pipeline checkpoint)
  notifications/                - future: slack.py, email.py

## Helm Chart

- x-sink (role=sink, enabled by default)
- x-sump (role=sump, enabled by default)
- checkpoint-s3 (role=regular, enabled if S3 configured)
- happy-end and error-end REMOVED

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md



---
**Close reason**: Two-layer termination implemented: asya-sink + asya-sump + configurable hooks. PR #182


---
_Migrated from beads `asya-5npu`_
