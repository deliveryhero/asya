---
title: "x-sump: emit OpenTelemetry metrics for hook outcomes"
priority: 3 # low
type: task
---

## Context

`x-sump` (`src/asya-crew/asya_crew/sump.py`) is the terminal actor for all messages — both
successful (routed via `x-sink` hooks) and failed (error path). It is the natural place to
emit final-lifecycle metrics for observability.

Currently sump only logs. The 1c46 RFC specified "Emits Prometheus metrics
(`hook_success` / `hook_failure`)" but this was deferred from PR #193.

## What to do

Add an OpenTelemetry counter in `sump_handler`:

```python
from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("asya.crew.sump")
_outcome_counter = _meter.create_counter(
    "asya.hook.outcome",
    description="Terminal message outcome at x-sump",
)

def sump_handler(message):
    ...
    _outcome_counter.add(1, {
        "actor": status.get("actor", "unknown"),
        "phase": phase,
        "reason": status.get("reason", ""),
    })
```

Configure OTEL via the existing `OTEL_EXPORTER_OTLP_ENDPOINT` env var (already injected by
Crossplane into crew pods — see `deploy/helm-charts/asya-crew/`).

Unit test: mock the counter and assert `add()` is called with the correct attribute dict for
both `failed` and `succeeded` phases.

## Files

- `src/asya-crew/asya_crew/sump.py` (primary)
- `src/asya-crew/tests/test_sump.py`
- `src/asya-crew/requirements.txt` (add `opentelemetry-api`)
