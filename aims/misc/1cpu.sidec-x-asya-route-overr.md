---
title: "Sidecar: x-asya-route-override header resolution"
status: open
priority: 2 # medium
type: task
---

## Summary

Implement the `x-asya-route-override` header resolution mechanism in the sidecar. When routing a message to the next actor, the sidecar checks if `headers["x-asya-route-override"]` contains a mapping for the target actor name, and if so, routes to the override queue instead.

## Protocol

From the A/B routing RFC:

```json
{
  "headers": {
    "x-asya-route-override": {
      "aggregator": "aggregator-2",
      "research_agent": "research_agent_v2"
    }
  }
}
```

When routing to actor `"aggregator"`, the sidecar looks up `x-asya-route-override["aggregator"]` and routes to `"aggregator-2"` queue instead.

After resolution, the sidecar stamps `x-asya-route-resolved` for audit trail:
```json
{
  "headers": {
    "x-asya-route-resolved": {
      "aggregator": "aggregator-2"
    }
  }
}
```

## Changes

### `src/asya-sidecar/internal/router/router.go`
- In the routing path (where the sidecar resolves the next actor queue name), add a lookup into `x-asya-route-override` header
- If override found: use the override queue name instead of the abstract actor name
- Stamp `x-asya-route-resolved` header with the resolution
- Must work for both normal routing (routeResponse) and fan-out routing (handleSuccessResponse)

### Tests
- Unit test: Override header resolves actor name to concrete queue
- Unit test: No override header → normal routing (no change)
- Unit test: Override for non-matching actor is ignored
- Unit test: `x-asya-route-resolved` audit header is set after resolution
- Unit test: Override works with fan-out (all children route to overridden queue)

## Dependencies
- DEPENDS ON: Sidecar header preservation (headers must survive routing first)

## References
- RFC: docs/rfc/a-b-testing/rfc-a-b-routing.md
- RFC: docs/rfc/fan-in/rfc-fan-in.md (Integration with A/B Routing)


---
_Migrated from beads `asya-2ozv`_
