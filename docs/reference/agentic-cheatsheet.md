<!-- Type: Reference -->

# Agentic Cheatsheet

Quick-reference tables for mapping ADK patterns to Asya equivalents and
using the ABI yield protocol in generator actors.

---

## ADK → Asya pattern map

| ADK pattern | Asya equivalent | Where |
|------------|----------------|-------|
| `SequentialAgent([A, B, C])` | Linear flow: `state = await A(state); state = await B(state)` | Flow DSL |
| `ParallelAgent([A, B, C])` | `asyncio.gather(A(x), B(x), C(x))` | Flow DSL |
| `LoopAgent(sub_agents, max=5)` | `while` loop in flow DSL | Flow DSL |
| `transfer_to_agent("X")` | `yield "SET", ".route.next", ["x"]` in generator actor | Actor (ABI) |
| `Event(partial=True, content=Part(text=t))` | `yield "FLY", {"partial": True, "text": t}` | Actor (ABI) |
| `should_pause_invocation()` | route to `x-pause`, set `_pause_metadata` | Actor (ABI) |
| `State` (delta-tracked) | `payload` dict (full state, JSON-serialized per hop) | Envelope |
| `output_key` enrichment | `payload["key"] = result` | Anywhere |
| `AgentTool` (agent-as-tool) | standard actor call (same dict→dict interface) | Flow DSL |
| `before/after_model_callback` | no direct equivalent (pre/post actor in pipeline) | Flow DSL |
| Session/conversation history | payload dict or state proxy | Payload / State proxy |

## ABI quick reference

```python
# Read metadata
value = yield "GET", ".route.prev"         # who processed this before
value = yield "GET", ".headers.trace_id"   # any header

# Rewrite routing
yield "SET", ".route.next", ["actor_a"]           # replace next
yield "SET", ".route.next[:0]", ["actor_a"]       # prepend to next
yield "SET", ".route.next[999:]", ["actor_a"]     # append to next

# Delete metadata
yield "DEL", ".headers.trace_id"

# Stream upstream to client (SSE)
yield "FLY", {"type": "text_delta", "token": "..."}
yield "FLY", {"type": "text_done"}

# Emit downstream payload (to next actor)
yield payload
```

---

## See also

| Topic | Document |
|-------|---------|
| ABI verb reference, path syntax, testing | `docs/reference/abi-protocol.md` |
| Flow DSL syntax, supported constructs | `docs/reference/flow-dsl.md` |
| Flow DSL examples (15 patterns) | `examples/flows/agentic/` |
| ABI handler examples (3 patterns) | `examples/actors/agentic/` |
| Agentic design concepts | [docs/explanation/agentic-design.md](../explanation/agentic-design.md) |
| Agentic patterns tutorial | [docs/tutorials/agentic-patterns.md](../tutorials/agentic-patterns.md) |
| Gateway security model (auth, dual-deployment) | `docs/architecture/gateway-security-model.md` |
| Envelope protocol and routing semantics | `docs/architecture/protocols/actor-actor.md` |
| State proxy and stateful actors | `src/asya-crew/asya_crew/` |
| AsyncActor XRD reference | `deploy/helm-charts/asya-crossplane/` |
