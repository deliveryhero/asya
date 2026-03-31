# Long-Running Agentic Workflows with Checkpoints

## Use-Case

Research agent that takes hours or days — literature review, hypothesis
generation, experiment design, (human approval), execution, analysis,
report writing. Or: multi-day onboarding pipeline, compliance audit,
due diligence investigation.

The "overnight agent" pattern: kick off a complex pipeline, go to sleep,
find results in the morning — with human gates at critical decision points.

## Why Asya

- **Durable queues = free checkpointing**: Messages survive pod restarts,
  cluster upgrades, and node failures. No checkpoint code needed. RabbitMQ/SQS
  provides durability that in-process frameworks must implement manually.
- **Pause/resume is native**: Route to `x-pause` — envelope checkpointed to
  S3. A researcher reviews days later, adds feedback, resumes. No timeout
  pressure (unlike in-process agents with 48h limits).
- **State-proxy for research artifacts**: Papers, datasets, intermediate
  results stored in S3 — actors read/write via standard Python file I/O.
- **Independent scaling**: Research actors (API-heavy, slow) scale differently
  from analysis actors (compute-heavy, fast).
- **Audit trail**: Envelope carries full processing history. Compliance team
  can inspect any request's journey through the pipeline.

## Architecture

```
Literature Review (hours)
      |
Hypothesis Generator
      |
Experiment Designer
      |
x-pause ──> [Human reviews experiment plan, days later]
      |
x-resume (with feedback)
      |
Experiment Executor (hours)
      |
Results Analyzer
      |
Report Writer
      |
x-pause ──> [Human reviews report, hours later]
      |
x-resume (with edits)
      |
Final Publisher
      |
x-sink
```

## Example Flow

```python
@flow
async def research_pipeline(p):
    p = await literature_review(p)
    p = await hypothesis_generator(p)
    p = await experiment_designer(p)

    # Human checkpoint 1: approve experiment
    p = await approval_gate(p)  # routes to x-pause internally

    p = await experiment_executor(p)
    p = await results_analyzer(p)
    p = await report_writer(p)

    # Human checkpoint 2: approve report
    p = await review_gate(p)  # routes to x-pause internally

    p = await final_publisher(p)
    return p
```

## Key Properties

- **No inherent timeout**: Message sits in queue or S3 checkpoint indefinitely
- **Resumable from exact point**: x-resume restores full route.next
- **Timeout budget pausing**: Timer frozen on pause, thawed on resume
- **Artifact persistence**: State-proxy S3 mount survives across all steps
