---
title: "E2E test: compiled flow with fan-out/fan-in on Kind cluster"
priority: 2 # medium
type: task
tags:
  - pr:210
dependencies:
  - 1c7i/1fr7i0
  - 1c7i/1fci1o
  - 1c7i/1i4xwg
  - 1c7i/1isz5r
---






## Summary

End-to-end test for a compiled Flow DSL program that includes fan-out/fan-in, deployed on a Kind cluster with aggregator using S3 state proxy sidecar (fanin-s3 flavor).

## Test Flow

```python
def research_flow(p: dict) -> dict:
    p["results"] = [research_agent(t) for t in p["topics"]]
    p = summarizer(p)
    return p
```

Compiled to:
- start router (mutation)
- fan-out router (generated, no sharding by default)
- research_agent actor (simple handler)
- aggregator (single Deployment, S3 state proxy sidecar with split-key pattern)
- summarizer actor (simple handler)

## Test Scenarios

1. **Happy path**: Submit message with 3 topics, verify aggregated results arrive at x-sink with correct order
2. **Gateway tracking**: Verify gateway SSE stream shows correct status updates (no false positives from partial fan-in messages)
3. **Scale**: Submit message with 10 topics, verify all 10 results aggregated
4. **Persistence**: Restart aggregator pod mid-aggregation, verify fan-in completes after restart (state is in S3, not on pod)

## Dependencies
- DEPENDS ON: Fan-out router code generator (1fr7i0)
- DEPENDS ON: Aggregator crew actor (fanin-s3 flavor)
- DEPENDS ON: Sidecar header preservation (1fci1o)
- DEPENDS ON: Sink non-reporting for x-asya-fan-in headers
- DEPENDS ON: State proxy sidecar (epic 1dmf) for S3 access

## References
- Fan-in RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Deployment)


---
_Migrated from beads `asya-1mqw`_
