---
title: "Sidecar: ASYA_ACTOR_ROLE (regular|sink|sump) and ASYA_ACTOR_SINK unification"
priority: 2 # medium
---




Refactor sidecar config to support the two-layer termination scheme:

1. Replace ASYA_IS_END_ACTOR (bool) with ASYA_ACTOR_ROLE (string: regular|sink|sump)
   - regular: reports intermediate progress, routes responses normally
   - sink: reports final status to gateway, routes handler responses (to hooks)
   - sump: emits Prometheus metrics, logs errors, terminal (no routing)

2. Unify ASYA_ACTOR_HAPPY_END + ASYA_ACTOR_ERROR_END into ASYA_ACTOR_SINK
   - Default: asya-sink
   - Both succeeded and failed messages go to the same sink
   - status.phase distinguishes the outcome

3. Update processEndActorMessage to handle sink role:
   - Report to gateway (like current end actor)
   - BUT also route handler responses (unlike current end actor)
   - Skip route validation (like current end actor)

4. Add sump role handling:
   - Terminal: ACK, emit metrics, no routing
   - No gateway reporting
   - Optional: log error messages to stdout

5. Update injector to set ASYA_ACTOR_ROLE based on actor name

RFC: docs/rfc/error-handing/rfc-error-handing.md (System Actors / Sidecar Actor Roles)
Depends on: PR #182 (crew handlers)


---
_Migrated from beads `asya-8jnz`_
