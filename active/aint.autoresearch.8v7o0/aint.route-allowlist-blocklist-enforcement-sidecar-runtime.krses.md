---
title: Route allowlist/blocklist enforcement in sidecar and runtime
status: open
priority: 1 # high
tags: [tier-3, autoresearch, runtime, security]
---

## Context

When an actor does `yield "SET", ".route.next", [...]`, the runtime currently
accepts any target. For autoresearch (and safety generally), we need to restrict
which actors a given handler can route to.

Use case: orchestrator-brain in a compiled flow should NOT be able to route
directly to x-sink (bypassing evaluation). The flow compiler knows the valid
topology — we should enforce it at runtime.

## Design

### AsyncActor manifest

```yaml
spec:
  routing:
    allowlist: ["train-model", "eval-model", "orchestrator-brain"]  # only these
    # OR
    blocklist: ["x-sink", "x-sump"]  # everything except these
```

Allowlist and blocklist are mutually exclusive. If neither is set, all targets
are allowed (backwards compatible).

### Sidecar enforcement

The sidecar reads the routing policy from the actor spec (passed via env var
`ASYA_ROUTE_ALLOWLIST` / `ASYA_ROUTE_BLOCKLIST`). When it receives the envelope
from the runtime with a rewritten `route.next`, it validates each target against
the policy. Rejected targets → envelope routed to x-sump with error.

### Runtime enforcement (belt + suspenders)

In `asya_runtime.py`, when the handler does `yield "SET", ".route.next", [...]`,
the runtime checks the targets against the policy BEFORE accepting the yield.
On violation, raises `RoutingError("target 'x-sink' is not in allowlist")` —
a Python exception the handler can catch or let propagate.

This gives immediate feedback to LLM-generated code (the error appears in
the handler's execution context) rather than a silent sidecar rejection.

### Compiled flows (automatic)

The flow compiler knows the valid topology. It should automatically generate
allowlists for each actor based on the compiled graph edges. No manual
configuration needed for flow-compiled actors.

## Testing

- Unit: runtime raises RoutingError on blocked target
- Unit: sidecar rejects envelope with blocked route.next
- Component: compiled flow generates correct allowlists
- E2E: LLM-generated yield "SET" to blocked target returns Python error
