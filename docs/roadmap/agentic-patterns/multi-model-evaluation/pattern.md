# Multi-Model Evaluation & Selection (Voting/Debate)

## Use-Case

Content generation where quality matters more than latency — marketing copy,
legal summaries, medical reports, code reviews. Multiple LLMs generate
candidates in parallel; a judge selects the best. Optionally, multi-round
debate where agents see each other's outputs and refine.

## Why Asya

- **Fan-out to different models**: GPT-4, Claude, Gemini run as separate actors,
  each with its own API key, rate limits, and resource quotas.
- **Actors are model-agnostic**: Each actor is `dict -> dict`. Swap the model by
  changing a ConfigMap env var, not code. Same handler, different `MODEL_NAME`.
- **Independent failure domains**: If one provider is down, its actor retries or
  routes to DLQ. The others continue and the judge works with available results.
- **Debate pattern**: Multi-round refinement where agents see each other's outputs.
  Each round is a fan-out + fan-in cycle inside a while loop.
- **State-in-message carries all drafts**: The judge actor sees
  `payload["drafts"]` with all candidates and their revision history across
  all debate rounds.

## Architecture (Voting)

```
Input
  |
  +---+---+---+
  |   |   |   |  (fan-out: same prompt, different models)
  v   v   v   v
 GPT Claude Gem Llama
  |   |   |   |
  +---+---+---+  (fan-in)
  |
  Judge (selects best, explains why)
  |
  x-sink
```

## Architecture (Debate)

```
Input
  |
  [fan-out: initial positions]
  |
  [while not converged, max 3 rounds]
      |
      [fan-out: each agent revises seeing all others]
      |
      [fan-in: collect revised positions]
      |
      Convergence Checker
  |
  Final Judge (synthesizes consensus)
  |
  x-sink
```

## Example Flow (Voting)

```python
@flow
async def voting_ensemble(p):
    p["candidates"] = await asyncio.gather(
        creative_writer(p),     # temperature=0.9
        analytical_writer(p),   # temperature=0.3
        concise_writer(p),      # max_tokens=200
    )
    p = await judge(p)
    return p
```

## Example Flow (Debate)

```python
@flow
async def multi_agent_debate(p):
    p["positions"] = await asyncio.gather(
        debater_optimist(p),
        debater_skeptic(p),
        debater_pragmatist(p),
    )
    p["round"] = 0
    while p["round"] < 3:
        p["round"] += 1
        p["positions"] = await asyncio.gather(
            revise_optimist(p),
            revise_skeptic(p),
            revise_pragmatist(p),
        )
        p = await convergence_checker(p)
        if p["converged"]:
            break
    p = await final_judge(p)
    return p
```
