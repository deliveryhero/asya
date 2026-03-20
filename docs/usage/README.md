# Build AI Actors

Write Python functions, deploy as Kubernetes actors, chain into meshes.

## Getting Started

Build and deploy your first actors:

- **[First Actor](start-first-actor.md)** — Build an echo actor, deploy, send a message, verify the result
- **[First Actor Mesh](start-first-actor-mesh.md)** — Chain two actors via route.next, trace the envelope at each hop
- **[First Flow](start-first-flow.md)** — Write a Flow DSL file, compile, inspect generated routers, deploy

## Guides

Patterns and techniques for actor development:

- **[Handler Patterns](guide-handler-patterns.md)** — Adapter pattern, generator vs function handlers, typed outputs
- **[Agentic Patterns](guide-agentic-patterns.md)** — Fan-out, dynamic routing, conditional branching, streaming
- **[Streaming](guide-streaming.md)** — FLY events, SSE, live progress to gateway clients
- **[Actor Flavors](guide-actor-flavors.md)** — Choose and use flavors in actor specs
- **[State Proxy](guide-state-proxy.md)** — Read/write `/state/` paths in handlers
- **[Pause/Resume](guide-pause-resume.md)** — Yield SET to x-pause, handle resume input
- **[Timeouts](guide-timeouts.md)** — Set actorTimeout, understand deadline behavior

## Operations

- **[Debugging](ops-debugging.md)** — Trace envelopes by trace_id, curl the runtime, check x-sink/x-sump
