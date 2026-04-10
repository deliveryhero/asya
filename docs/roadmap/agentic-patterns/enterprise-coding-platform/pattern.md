# Agentic Research & Development Platform

## The Problem

Researchers and engineers need to run large-scale agentic tasks — deep research
across 10 topics in parallel, iterative experiment-evaluate loops, multi-agent
code analysis across 20 repos. Today this means either running sequentially on
one machine (slow) or building ad-hoc infrastructure for each project (wasteful).

## The Insight

**A research task IS a flow.** Fan-out 10 researchers, fan-in to an evaluator,
loop if coverage is insufficient, write artifacts to S3. All actors ephemeral,
state in the message, heavy artifacts in state-proxy. The "platform" is just
"a Kubernetes cluster running Asya with state-proxy mounts to shared data."

No special workbench pods. No heartbeat hacks. No new concepts. The Flow DSL
already supports every agentic pattern a researcher needs.

## Architecture

```
Researcher (local machine, remote VM, IDE, terminal — anywhere)
  |
  | 1. Write flow in Python
  | 2. asya flow compile research.py
  | 3. kubectl apply -f compiled/manifests/
  | 4. Trigger via gateway: POST /mcp tools/call or POST /a2a/
  |
  v
Asya Mesh (all actors ephemeral, KEDA-scaled)

  Orchestrator
      |
      | [fan-out: N researcher actors in parallel]
      |
  +---+---+---+---+
  |   |   |   |   |
  R1  R2  R3  ... RN    (each: search → analyze → write findings)
  |   |   |   |   |
  +---+---+---+---+
      |
      | [fan-in: aggregate all findings]
      |
  Evaluator
      |
      | [if coverage < threshold: refine queries, loop]
      | [if coverage >= threshold: break]
      |
  Synthesizer (final report)
      |
  x-sink → results in envelope payload
           + heavy artifacts in state-proxy S3
```

## Why Asya (The Actor Model Advantage)

The flow compiles to a graph of stateless, ephemeral actors. Each actor:

1. **Receives an envelope** with the full research context (all previous
   findings, evaluation scores, refined queries) in the payload
2. **Does its work** (web search, LLM analysis, code scan, experiment)
3. **Enriches the payload** with its results
4. **Yields the envelope** to the next actor in the route
5. **Dies** (pod scales to zero when queue is empty)

No shared mutable state. No long-running processes. No heartbeats. If a pod
crashes mid-work, the queue retries. If you need 10 researchers, KEDA scales
to 10 pods. When they're done, KEDA scales back to zero.

State-proxy is for **heavy artifacts only** — datasets, model weights, generated
reports. The research context itself travels in the message.

## Example Flows

### Deep Research (Fan-Out + Evaluate Loop)

```python
@flow
async def deep_research(p):
    p = await plan_research(p)           # decompose into sub-topics

    p["iteration"] = 0
    while p["iteration"] < 3:
        p["iteration"] += 1

        # Fan-out: one researcher per sub-topic
        p["findings"] = [
            researcher(topic) for topic in p["sub_topics"]
        ]

        p = await evaluator(p)           # score coverage, identify gaps
        if p["coverage"] >= 0.85:
            break
        p = await query_refiner(p)       # refine queries for next round

    p = await synthesizer(p)             # final report from all findings
    return p
```

### Multi-Repo Code Analysis

```python
@flow
async def code_audit(p):
    # Fan-out: one scanner per repository
    p["scan_results"] = [
        security_scanner(repo) for repo in p["repositories"]
    ]
    p = await vulnerability_aggregator(p)
    p = await severity_classifier(p)

    if p["critical_count"] > 0:
        p = await remediation_advisor(p)  # suggest fixes

    return p
```

### Experiment Grid Search

```python
@flow
async def hyperparameter_search(p):
    # Fan-out: one trainer per config
    p["results"] = [
        train_and_evaluate(config) for config in p["grid"]
    ]
    p = await result_ranker(p)           # rank by metric
    p = await report_generator(p)        # summary + charts
    return p
```

### ReAct Agent with Tool Loop

```python
@flow
async def research_agent(p):
    p["messages"] = []
    while True:
        p = await llm_reason(p)          # decide next action
        if not p.get("tool_calls"):
            break                        # final answer
        p = await tool_executor(p)       # run tool, append observation
    return p
```

## State-Proxy for Heavy Artifacts

State in the message handles research context (findings, scores, queries).
State-proxy handles heavy artifacts that shouldn't travel in envelopes:

```python
# Researcher actor writes large dataset analysis to S3
async def researcher(payload):
    results = await heavy_analysis(payload["topic"])

    # Large artifact → state-proxy (not in message)
    with open(f"/state/artifacts/{payload['topic']}.json", "w") as f:
        json.dump(results["detailed_analysis"], f)

    # Summary → message payload (travels with envelope)
    payload["findings"] = results["summary"]
    payload["artifact_path"] = f"/state/artifacts/{payload['topic']}.json"
    return payload
```

Downstream actors read artifacts from state-proxy when needed:
```python
async def synthesizer(payload):
    for finding in payload["findings"]:
        if finding.get("artifact_path"):
            with open(finding["artifact_path"]) as f:
                details = json.load(f)
            # Use details for deeper synthesis
    ...
```

## Enterprise Platform Layer

For a DevX team providing this company-wide:

### What the Platform Team Provides

- **The cluster**: Kubernetes with Asya (Crossplane, KEDA, transport, gateway)
- **State-proxy mounts**: Pre-configured S3 buckets per team/project with datasets
- **Container images**: Per-tech-stack images (Python+DS, Node, Go, Java) with
  standard toolchains and pre-installed dependencies
- **Gateway**: MCP/A2A endpoint for triggering flows, streaming progress, auth
- **GPU node pools**: KEDA-scaled GPU actors for ML workloads
- **Cost attribution**: Per-user/team compute + LLM token tracking via metrics

### What the Researcher Does

1. Writes a flow in Python (using Flow DSL)
2. Compiles: `asya flow compile research.py`
3. Deploys: `kubectl apply -f compiled/manifests/`
4. Triggers: `POST /mcp tools/call` or `asya mcp send`
5. Monitors: FLY events stream progress in real-time
6. Reads results: In the final envelope payload or state-proxy S3

### Scaling Properties

| Dimension | How It Scales |
|---|---|
| More topics/repos | Fan-out: more messages → KEDA scales more pods |
| Deeper research | Loop iterations: evaluator controls convergence |
| More users/teams | Namespace isolation: each team's actors independent |
| Larger artifacts | State-proxy S3: unlimited storage, actors remain stateless |
| GPU workloads | Node selectors + tolerations: GPU actors on GPU nodes |
