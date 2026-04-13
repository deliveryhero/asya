here's old implementation plan - actualize it and prepare new tasks for current epic.
     ╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
     │ Plan: asya-qrsp — Multi-Frame Streaming Protocol (Sidecar)                                                                                                                                 │
     │                                                                                                                                                                                            │
     │ Context                                                                                                                                                                                    │
     │                                                                                                                                                                                            │
     │ The sidecar's wire protocol currently treats ALL non-end frames as result frames. For agentic workloads (LLM streaming, progress updates), we need to distinguish between:                 │
     │ - Streaming events — intermediate updates (text deltas, progress) that propagate through the flow pipeline                                                                                 │
     │ - Result frames — final processing results routed to the next actor queue                                                                                                                  │
     │                                                                                                                                                                                            │
     │ Issue asya-qrsp extends the sidecar's frame reader to recognize streaming events vs result frames, with A2A-aligned schema and proper event propagation for flow composition.              │
     │                                                                                                                                                                                            │
     │ Scope boundary: The actual HTTP forwarding endpoint on the gateway is asya-n5mc. This issue adds protocol support, event routing logic, and the callback mechanism.                        │
     │                                                                                                                                                                                            │
     │ Step 0: Update RFC and Beads                                                                                                                                                               │
     │                                                                                                                                                                                            │
     │ Before writing code, update existing documentation with the A2A alignment findings:                                                                                                        │
     │                                                                                                                                                                                            │
     │ 0a. Update RFC Section 11.1 (agentic-compiler-rfc.md)                                                                                                                                      │
     │                                                                                                                                                                                            │
     │ Replace the "direct-to-gateway" streaming design:                                                                                                                                          │
     │ // OLD: blind send to gateway                                                                                                                                                              │
     │ case "stream":                                                                                                                                                                             │
     │     forwardToGateway(frame.Data, envelopeID)                                                                                                                                               │
     │                                                                                                                                                                                            │
     │ With route-based event propagation:                                                                                                                                                        │
     │ // NEW: events follow the route, like results                                                                                                                                              │
     │ case "artifact-update", "status-update":                                                                                                                                                   │
     │     if hasNextActor(route) {                                                                                                                                                               │
     │         routeToNextActor(frame)  // Propagate up through pipeline                                                                                                                          │
     │     } else {                                                                                                                                                                               │
     │         forwardToGateway(frame)  // Root level: stream to client                                                                                                                           │
     │     }                                                                                                                                                                                      │
     │                                                                                                                                                                                            │
     │ Also update Section 10.3 frame format to use A2A-aligned kind discriminator.                                                                                                               │
     │                                                                                                                                                                                            │
     │ 0b. Update beads asya-qrsp description                                                                                                                                                     │
     │                                                                                                                                                                                            │
     │ Update the issue description to reflect:                                                                                                                                                   │
     │ - A2A-aligned frame format (kind discriminator, artifact-update/status-update event types)                                                                                                 │
     │ - Route-based event propagation (not direct-to-gateway)                                                                                                                                    │
     │ - last_chunk, append, final semantics from A2A                                                                                                                                             │
     │                                                                                                                                                                                            │
     │ File: .worktrees/rfc0/docs/rfc/agentic-compiler/agentic-compiler-rfc.md (Sections 10.3, 11.1)                                                                                              │
     │                                                                                                                                                                                            │
     │ ---                                                                                                                                                                                        │
     │ Event Propagation Design: Route-Based (ADK-Style Bubble-Up)                                                                                                                                │
     │                                                                                                                                                                                            │
     │ Problem with Direct-to-Gateway                                                                                                                                                             │
     │                                                                                                                                                                                            │
     │ The original RFC Section 11.1 proposed sending streaming events directly from any actor's sidecar to the gateway. This prevents flow composition:                                          │
     │                                                                                                                                                                                            │
     │ async def root_flow(p: dict):                                                                                                                                                              │
     │     async for event in sequential_agent_flow(p):                                                                                                                                           │
     │         if event["kind"] != "end":                                                                                                                                                         │
     │             event = await call_finalizer(event)  # Transform events!                                                                                                                       │
     │         yield event                                                                                                                                                                        │
     │                                                                                                                                                                                            │
     │ If sequential_agent_flow sends events directly to the gateway, root_flow never gets to transform them via call_finalizer.                                                                  │
     │                                                                                                                                                                                            │
     │ Solution: Events Follow the Route                                                                                                                                                          │
     │                                                                                                                                                                                            │
     │ Events are routed the same way as results — to the next actor in the route. Only when there's no next actor does the sidecar forward events to the gateway.                                │
     │                                                                                                                                                                                            │
     │ Inner actor yields event:                                                                                                                                                                  │
     │   → Sidecar checks route: has next actor? YES → route to next queue                                                                                                                        │
     │   → Next actor receives event, processes/transforms it, yields                                                                                                                             │
     │   → Sidecar checks route: has next actor? NO → forward to gateway                                                                                                                          │
     │                                                                                                                                                                                            │
     │ This enables flow composition where parent flows can intercept, transform, and filter streaming events from child flows — matching ADK's event bubble-up model.                            │
     │                                                                                                                                                                                            │
     │ Routing Logic                                                                                                                                                                              │
     │                                                                                                                                                                                            │
     │ The sidecar's routeFrame() logic:                                                                                                                                                          │
     │ ┌────────────────────────────────┬─────────────────┬─────────────────────────────────────────────────┐                                                                                     │
     │ │           Frame kind           │ Has next actor? │                     Action                      │                                                                                     │
     │ ├────────────────────────────────┼─────────────────┼─────────────────────────────────────────────────┤                                                                                     │
     │ │ artifact-update, status-update │ YES             │ Route to next actor's queue (propagate up)      │                                                                                     │
     │ ├────────────────────────────────┼─────────────────┼─────────────────────────────────────────────────┤                                                                                     │
     │ │ artifact-update, status-update │ NO              │ Forward to gateway (root level)                 │                                                                                     │
     │ ├────────────────────────────────┼─────────────────┼─────────────────────────────────────────────────┤                                                                                     │
     │ │ result or legacy (no kind)     │ YES             │ Route to next actor's queue (existing behavior) │                                                                                     │
     │ ├────────────────────────────────┼─────────────────┼─────────────────────────────────────────────────┤                                                                                     │
     │ │ result or legacy (no kind)     │ NO              │ Route to happy-end (existing behavior)          │                                                                                     │
     │ ├────────────────────────────────┼─────────────────┼─────────────────────────────────────────────────┤                                                                                     │
     │ │ end                            │ —               │ Terminate frame loop                            │                                                                                     │
     │ └────────────────────────────────┴─────────────────┴─────────────────────────────────────────────────┘                                                                                     │
     │ Key: Events never go to happy-end. At the end of the route, events go to the gateway; results go to happy-end.                                                                             │
     │                                                                                                                                                                                            │
     │ Why the Route Is Sufficient                                                                                                                                                                │
     │                                                                                                                                                                                            │
     │ In asya's compiled flow model, all actors (including inner flows) share one flat route that gets dynamically modified by routers. The sidecar doesn't need to know if it's in a "root      │
     │ flow" or "inner flow" — it just follows the route:                                                                                                                                         │
     │ - Has next actor → forward to next queue                                                                                                                                                   │
     │ - No next actor → gateway (events) or happy-end (results)                                                                                                                                  │
     │                                                                                                                                                                                            │
     │ The asya.sh/flow and asya.sh/flow-role labels are used for monitoring/debugging, not routing decisions.                                                                                    │
     │                                                                                                                                                                                            │
     │ ---                                                                                                                                                                                        │
     │ Protocol Design — A2A Aligned                                                                                                                                                              │
     │                                                                                                                                                                                            │
     │ Discriminator: kind field                                                                                                                                                                  │
     │                                                                                                                                                                                            │
     │ A2A uses kind as its event type discriminator. Our new protocol adopts kind for all new frame types. Legacy frames continue using type: "end" for backward compat.                         │
     │                                                                                                                                                                                            │
     │ Frame Types                                                                                                                                                                                │
     │                                                                                                                                                                                            │
     │ # A2A artifact-update event (LLM text streaming, file chunks):                                                                                                                             │
     │ {"kind": "artifact-update", "artifact": {"parts": [{"kind": "text", "text": "Hello "}]}, "append": true, "last_chunk": false}                                                              │
     │                                                                                                                                                                                            │
     │ # A2A status-update event (progress, state changes):                                                                                                                                       │
     │ {"kind": "status-update", "status": {"state": "working"}, "final": false}                                                                                                                  │
     │                                                                                                                                                                                            │
     │ # Result frame (same structure as legacy, with explicit kind):                                                                                                                             │
     │ {"kind": "result", "payload": {...}, "route": {...}}                                                                                                                                       │
     │                                                                                                                                                                                            │
     │ # End sentinel (new):                                                                                                                                                                      │
     │ {"kind": "end"}                                                                                                                                                                            │
     │                                                                                                                                                                                            │
     │ # Legacy end sentinel (backward compat):                                                                                                                                                   │
     │ {"type": "end"}                                                                                                                                                                            │
     │                                                                                                                                                                                            │
     │ # Legacy result frame (backward compat, no kind or type):                                                                                                                                  │
     │ {"payload": {...}, "route": {...}}                                                                                                                                                         │
     │                                                                                                                                                                                            │
     │ A2A Schema Reference                                                                                                                                                                       │
     │                                                                                                                                                                                            │
     │ TaskArtifactUpdateEvent fields: artifact.parts[] (with kind: text/file/data), append, last_chunk, metadata                                                                                 │
     │                                                                                                                                                                                            │
     │ TaskStatusUpdateEvent fields: status.state (submitted/working/input-required/completed/canceled/failed/rejected/auth-required), status.message, final                                      │
     │                                                                                                                                                                                            │
     │ Part types: TextPart (kind: "text", text), FilePart (kind: "file", file), DataPart (kind: "data", data)                                                                                    │
     │                                                                                                                                                                                            │
     │ Note: task_id/context_id are NOT in wire frames — the sidecar wraps events in a message envelope with the existing message ID when routing through queues.                                 │
     │                                                                                                                                                                                            │
     │ Parsing Strategy                                                                                                                                                                           │
     │                                                                                                                                                                                            │
     │ frameHeader { Kind string `json:"kind"`; Type string `json:"type"` }                                                                                                                       │
     │                                                                                                                                                                                            │
     │ 1. Read raw frame bytes via RecvSocketData                                                                                                                                                 │
     │ 2. Minimal parse: extract kind and type fields                                                                                                                                             │
     │ 3. Dispatch:                                                                                                                                                                               │
     │    kind ∈ {"artifact-update", "status-update"} → streaming event → call onEvent + route via queue or gateway                                                                               │
     │    kind == "result"                             → unmarshal as RuntimeResponse                                                                                                             │
     │    kind == "end" OR type == "end"               → break loop                                                                                                                               │
     │    no kind + no type                            → unmarshal as RuntimeResponse (legacy)                                                                                                    │
     │                                                                                                                                                                                            │
     │ json.RawMessage Optimization                                                                                                                                                               │
     │                                                                                                                                                                                            │
     │ Streaming event frames are forwarded as raw []byte. The sidecar never parses event content beyond the kind field, preserving zero-copy forwarding for queue routing and gateway            │
     │ forwarding.                                                                                                                                                                                │
     │                                                                                                                                                                                            │
     │ ---                                                                                                                                                                                        │
     │ Files to Modify                                                                                                                                                                            │
     │                                                                                                                                                                                            │
     │ 1. src/asya-sidecar/internal/runtime/client.go                                                                                                                                             │
     │                                                                                                                                                                                            │
     │ Add types:                                                                                                                                                                                 │
     │ // EventCallback is called for each A2A streaming event with the raw frame bytes.                                                                                                          │
     │ type EventCallback func(data []byte)                                                                                                                                                       │
     │                                                                                                                                                                                            │
     │ // frameHeader extracts discriminator fields for minimal frame dispatch.                                                                                                                   │
     │ type frameHeader struct {                                                                                                                                                                  │
     │     Kind string `json:"kind"` // A2A-aligned discriminator (new protocol)                                                                                                                  │
     │     Type string `json:"type"` // Legacy discriminator (backward compat)                                                                                                                    │
     │ }                                                                                                                                                                                          │
     │                                                                                                                                                                                            │
     │ // isEvent returns true if the frame is an A2A streaming event.                                                                                                                            │
     │ func (h *frameHeader) isEvent() bool {                                                                                                                                                     │
     │     return h.Kind == "artifact-update" || h.Kind == "status-update"                                                                                                                        │
     │ }                                                                                                                                                                                          │
     │                                                                                                                                                                                            │
     │ Update CallRuntime signature:                                                                                                                                                              │
     │ func (c *Client) CallRuntime(ctx context.Context, data []byte, onEvent EventCallback) ([]RuntimeResponse, error)                                                                           │
     │                                                                                                                                                                                            │
     │ Update frame reading loop — dispatch by kind/type as described above. Events invoke onEvent callback; results append to response slice.                                                    │
     │                                                                                                                                                                                            │
     │ 2. src/asya-sidecar/internal/runtime/client_test.go                                                                                                                                        │
     │                                                                                                                                                                                            │
     │ New tests:                                                                                                                                                                                 │
     │ - TestClient_CallRuntime_EventsAndResult — artifact-update + status-update events, then result; verify callback count and result                                                           │
     │ - TestClient_CallRuntime_EventsOnly — events with no result; verify empty results                                                                                                          │
     │ - TestClient_CallRuntime_ResultWithKind — result with explicit kind: "result"                                                                                                              │
     │ - TestClient_CallRuntime_LegacyBackwardCompat — frames with no kind still work                                                                                                             │
     │ - TestClient_CallRuntime_NilEventCallback — events with nil callback don't crash                                                                                                           │
     │ - TestClient_CallRuntime_MalformedFrame — malformed frame error handling                                                                                                                   │
     │                                                                                                                                                                                            │
     │ Update existing tests: pass nil as onEvent.                                                                                                                                                │
     │                                                                                                                                                                                            │
     │ 3. src/asya-sidecar/internal/router/router.go                                                                                                                                              │
     │                                                                                                                                                                                            │
     │ Update CallRuntime calls to pass an event callback:                                                                                                                                        │
     │ - For the main path: pass a callback that routes events via routeEventFrame()                                                                                                              │
     │ - For end actors: pass nil (end actors don't propagate events)                                                                                                                             │
     │                                                                                                                                                                                            │
     │ Add routeEventFrame() method:                                                                                                                                                              │
     │ func (r *Router) routeEventFrame(ctx context.Context, msg *messages.Message, eventData []byte) {                                                                                           │
     │     nextActor := msg.Route.GetNextActor()  // actor after current                                                                                                                          │
     │     if nextActor != "" {                                                                                                                                                                   │
     │         // Inner flow: route event to next actor's queue                                                                                                                                   │
     │         r.routeEventToQueue(ctx, msg, eventData, nextActor)                                                                                                                                │
     │     } else if r.gatewayURL != "" {                                                                                                                                                         │
     │         // Root level: forward to gateway                                                                                                                                                  │
     │         r.forwardEventToGateway(ctx, msg.ID, eventData)                                                                                                                                    │
     │     }                                                                                                                                                                                      │
     │     // else: no destination, drop silently                                                                                                                                                 │
     │ }                                                                                                                                                                                          │
     │                                                                                                                                                                                            │
     │ routeEventToQueue: Wraps event data in a message envelope (with id, route incremented, kind preserved) and sends to next queue. The downstream actor's runtime receives it and the handler │
     │  can process/transform the event.                                                                                                                                                          │
     │                                                                                                                                                                                            │
     │ forwardEventToGateway: HTTP POST to gateway's event endpoint (implementation deferred to asya-n5mc; for now, log and drop).                                                                │
     │                                                                                                                                                                                            │
     │ 4. src/asya-sidecar/internal/router/router_test.go                                                                                                                                         │
     │                                                                                                                                                                                            │
     │ Update test helpers and mock calls for new CallRuntime signature.                                                                                                                          │
     │                                                                                                                                                                                            │
     │ New tests:                                                                                                                                                                                 │
     │ - TestRouter_EventRouting_NextActor — event routed to next actor queue when route has more actors                                                                                          │
     │ - TestRouter_EventRouting_NoNextActor — event forwarded (logged) when at route end                                                                                                         │
     │                                                                                                                                                                                            │
     │ 5. src/asya-sidecar/pkg/messages/message.go (if needed)                                                                                                                                    │
     │                                                                                                                                                                                            │
     │ Check if Route has a GetNextActor() method. If not, add one that returns the actor at current + 1 (or empty string if at end).                                                             │
     │                                                                                                                                                                                            │
     │ ---                                                                                                                                                                                        │
     │ Verification                                                                                                                                                                               │
     │                                                                                                                                                                                            │
     │ 1. Run unit tests: make -C src/asya-sidecar test-unit                                                                                                                                      │
     │ 2. Run linter: make lint                                                                                                                                                                   │
     │ 3. All existing tests pass unchanged (backward compat)                                                                                                                                     │
     │ 4. New tests cover the issue test plan:                                                                                                                                                    │
     │   - Single frame backward compat                                                                                                                                                           │
     │   - Multiple streaming events + result frame                                                                                                                                               │
     │   - Event routing to next queue vs gateway                                                                                                                                                 │
     │   - Malformed frame handling                                                                                                                                                               │
     │                                                                                                                                                                                            │
     │ Workflow                                                                                                                                                                                   │
     │                                                                                                                                                                                            │
     │ 1. Create git worktree on branch asya-qrsp                                                                                                                                                 │
     │ 2. Update RFC and beads (Step 0)                                                                                                                                                           │
     │ 3. Implement sidecar changes                                                                                                                                                               │
     │ 4. Run make -C src/asya-sidecar test-unit                                                                                                                                                  │
     │ 5. Create PR targeting main                                                                                                                                                                │
     ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
