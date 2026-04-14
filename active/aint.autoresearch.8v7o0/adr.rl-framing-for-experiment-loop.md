# ADR: RL Framing for the Experiment Loop

**Status:** Accepted
**Date:** 2026-04-15

## Context

The autoresearch loop needs a principled structure. Options considered:
1. Ad-hoc loop (like Karpathy's autoresearch — edit, run, check, repeat)
2. RL-structured loop (state/action/environment/reward)
3. Full RL training (policy gradient updates on the orchestrator LLM)

## Decision

Use **RL-structured loop** as design vocabulary. The experiment loop maps to:
- State: experiment history + metrics + budget
- Action: hyperparams, architecture, data strategy (constrained action space)
- Environment: evaluation flow (immutable)
- Reward: evaluation metric
- Policy: LLM reasoning (zero-shot, not trained)

Formally, this is **Bayesian optimization with LLM as acquisition function**.

## Rationale

- **Clearer than ad-hoc**: RL vocabulary forces explicit definition of what's
  mutable (action) vs immutable (environment), what's the objective (reward),
  and what constrains the agent (budget, action space).
- **Safety properties**: evaluation immutability and route enforcement follow
  naturally from the "agent can't modify the environment" RL axiom.
- **More generic than Karpathy's loop**: action space and reward are
  parameterized per experiment, not hardcoded.
- **Simpler than full RL**: no policy training, no reward model, no replay
  buffer optimization. Memory state proxy provides few-shot context but no
  gradient signal.

## Consequences

- Experiment aint must define: action_space, environment (eval handler),
  reward (metric + threshold), budget
- Compiled flow enforces topology (agent can't skip environment)
- Route allowlists auto-generated from compiled graph
- LLM may be suboptimal compared to a trained policy — acceptable for v0,
  memory accumulation provides improvement over time
