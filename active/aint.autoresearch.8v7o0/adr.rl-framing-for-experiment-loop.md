# ADR: RL Framing for the Experiment Loop

**Status:** Accepted
**Date:** 2026-04-15

## Context

The autoresearch loop needs a principled structure. Options considered:
1. Ad-hoc loop (like Karpathy's autoresearch — edit, run, check, repeat)
2. RL-structured loop (state/action/environment/reward)
3. Full RL training (policy gradient updates on the orchestrator LLM)

The autoresearch loop is structurally an RL loop:

┌─────────────┬──────────────────────────────────────────────────────────┐
│ RL concept  │                 Autoresearch equivalent                  │
├─────────────┼──────────────────────────────────────────────────────────┤
│ State       │ experiment history + current metrics + memory            │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Action      │ hyperparams, architecture choice, data cleaning strategy │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Environment │ fixed evaluation flow (the "judge")                      │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Reward      │ evaluation metric (accuracy, F1, Spearman, etc.)         │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Policy      │ LLM reasoning (not a trained policy)                     │
├─────────────┼──────────────────────────────────────────────────────────┤
│ Episode     │ one full experiment run                                  │
└─────────────┴──────────────────────────────────────────────────────────┘

But — and this is the key — formalizing it as RL doesn't help us train the agent. We're not doing policy gradient updates on the LLM. We're using the LLM as a zero-shot or few-shot policy. The "learning" happens in the memory state proxy (accumulated observations), not in weight updates.

So the RL framing is useful as a design vocabulary (it clarifies: what's the state, what's the action space, what's immutable, what's the reward) but not as an optimization algorithm. What we're actually building is closer to:

Bayesian optimization with LLM as acquisition function — the LLM uses its world knowledge + experiment history (memory) to propose the most promising next experiment. It's not maximizing expected improvement over a GP posterior, but the structure is the same: observe results → reason about what to try next →
propose → evaluate.

This distinction matters for the design because:

1. The evaluation flow must be immutable (like an RL environment). The orchestrator can't modify the evaluation to game the reward. This is a hard architectural boundary, not just a convention.
2. The action space should be explicitly defined per experiment — not "do anything." The experiment aint specifies: "you may modify learning rate (0.0001-0.1), batch size (16-256), and architecture (resnet18/resnet50/efficientnet)." This constrains the orchestrator and prevents reward hacking.
3. The reward must be specified in the experiment aint — "accuracy on test set > 0.95" or "Spearman correlation > 0.8". Unambiguous, measurable.
4. Budget is explicit — max iterations, max parallel runs, max compute cost. Like your Yummy-Gym budget.

For your preference-cleaning task specifically: the orchestrator would fan-out N cleaning strategies (LLM-generated), each runs through a fixed judge (Spearman against held-out truth), results fan-in, orchestrator picks the best and iterates. Fits perfectly.

So yes — the generic autoresearch loop is an RL-structured loop, with these fixed roles:

EXPERIMENT AINT defines:
  - action_space: what the orchestrator may vary
  - environment: evaluation flow (immutable)
  - reward: metric + threshold
  - budget: iterations, parallelism, compute
  - initial_state: dataset, baseline code

ORCHESTRATOR FLOW (generic, deployed once):
  - reads experiment aint (state + action space + reward spec)
  - reads memory (past observations)
  - calls LLM with constrained action space → proposes N experiments
  - fans-out to training flows
  - fans-in results
  - evaluates reward
  - writes memory observation
  - loops or terminates

This is more generic than Karpathy's loop (which is hardcoded to "edit train.py, measure val_bpb") — the action space and reward are parameterized. But it's not full RL (no policy training). The LLM is the policy, memory is the experience replay buffer, but we never do gradient updates.


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
