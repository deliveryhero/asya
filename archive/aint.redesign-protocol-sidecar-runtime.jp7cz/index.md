---
title: Redesign Protocol Sidecar-Runtime
status: merged
priority: 2
children:
  - 1igop
  - 1ikcz
  - 1iofo
  - 1iuck
  - 1fqlf
  - 1ig1r
---

Replace the custom binary framing protocol between sidecar (Go) and runtime (Python) with **HTTP over Unix socket**. This enables streaming responses for generator handlers, standard error semantics, debuggability with curl, and future TCP mode for local testing.

## Motivation

The current protocol (`docs/architecture/protocols/sidecar-runtime.md`) uses a custom binary framing: 4-byte big-endian length prefix + JSON body, one connection per message, single request-response.

This protocol is insufficient for the [handler signatures redesign](.aim/aims/1c84.handler-signatures-wip/README.md) which introduces:

- **Generator handlers** that yield multiple downstream frames per invocation
- **Upstream partial frames** for token-by-token LLM streaming to the gateway
- **Mixed frame types** (downstream, upstream-partial, error) in a single response

Extending the binary protocol to handle multi-frame streaming means inventing custom framing, frame type headers, and done-signaling — which is reinventing HTTP badly.

## Key RFCs

- `.aint/aints/.closed/typed-handler-signatures/rfc.md` (REJECTED. handler signatures — the consumer of this protocol) - 
- `.aint/aints/.closed/stateful-actors/rfc.md` (stateful actors — also uses HTTP over Unix socket between runtime and state proxy sidecars)
