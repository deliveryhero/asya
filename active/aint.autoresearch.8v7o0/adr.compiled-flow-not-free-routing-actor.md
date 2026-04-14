# ADR: Compiled Flow, Not Free-Routing Actor for Orchestration

**Status:** Accepted
**Date:** 2026-04-15

## Context

The autoresearch orchestrator needs to loop: decide -> train -> evaluate ->
decide again. Two implementation options:

1. **Free-routing actor**: single actor with `yield "SET", ".route.next"` to
   dynamically route to train, eval, or x-sink. Maximum flexibility.
2. **Compiled flow**: flow DSL defines the loop topology, orchestrator-brain is
   a flow handler that returns structured decisions but cannot rewrite routes.

## Decision

Use a **compiled flow**. The orchestrator-brain is a flow handler, not a
free-routing actor.

## Rationale

- **Reward hacking prevention**: a free-routing orchestrator can bypass
  evaluation (`yield "SET", ".route.next", ["x-sink"]` with fabricated
  metrics). A compiled flow enforces the topology — evaluation cannot be
  skipped.
- **Route allowlists are automatic**: the flow compiler knows the graph edges
  and generates allowlists for each actor. No manual configuration.
- **Separation of concerns**: the brain decides WHAT to try (action),
  the flow decides HOW to execute it (topology). Clean boundary.
- **Auditability**: the compiled graph is inspectable (DOT/Mermaid/JSON).
  Reviewers can verify the loop structure before deployment.

## Consequences

- Orchestrator cannot dynamically change the flow topology (e.g., add a new
  actor type mid-experiment). Must redeploy the flow.
- For use cases requiring dynamic topology, use standalone actors (but these
  don't get the safety guarantees).
- The flow DSL must support while-loops with fan-out/fan-in (already exists
  in the compiler).
