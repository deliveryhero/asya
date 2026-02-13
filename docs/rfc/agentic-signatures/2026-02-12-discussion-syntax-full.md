I want to take a step back and clearly design the possible syntaxes for actor handlers in a new rfc. it has to be super simple, no extra pip packages, runnable locally as pure python with the same code semantics. for now, I want to think ONLY about async handlers - let's imagine all sync handlers are not supported anymore. All handlers should work on payload mode (so that receiving a payload only as argument - dict/typeddict/pydantic). an actor may either return a result (may be None for abort execution semantics), or yield one or more payloads:
- either partial=True to go "upstream" up to the gateway - see agent composition design .worktrees/rfc0/docs/rfc/agentic-signatures/asya-handler-syntax-comparisons.md
- or partial=False to go "downstream" down to the next actor in the route (classic).

My goal is:
- pre-compile standard flows for typical ReAct patterns (sequential agents, parallel agents, loop agents, etc) so that the user can just implement the agents prompts and confuguration, and asya will deploy it on these pre-compiled flows
- be able to compile custom flows for custom agents overloaded `async def _run_async_impl(self, ctx: InvocationContext)` - see https://google.github.io/adk-docs/agents/custom-agents/
- natively support ADK syntax:
```
async for event in self.some_sub_agent.run_async(ctx):
    # Optionally inspect or log the event
    yield event # may be partial or non-partial - this is actor composition
```
- natively support "traditional" (simple business logic) actors in the simplest way possible.
- allow users to implement routers with the same signatures as regular actors (a router is an actor that has access to `route` and `headers` of the message and can send payloads via yield or return to different routes with different headers). Ideally any actor should have access to headers, for example to get trace id and send custom otel metric. so i'd not differentiate anymore between routers and traditional processor-actors, just call them actors.
- I was told that current sync signatures `def handler(payload: dict) -> dict` and `def handler(envelope: dict) -> dict` are too confusing for Data Scientists because of overloading semantics with the same typing signature.

Example message format:
```
{
  "id": "msg-abc-123",
  "route": {"actors": ["actor-a", "actor-b", "actor-c"], "current": 1},
  "headers": {"trace_id": "xyz-789"},
  "payload": {...},
  "status": {
    "phase": "processing",
    "actor": "actor-b",
    "attempt": 1,
    "max_attempts": 5,
    "created_at": "2025-06-15T10:30:00Z",
    "updated_at": "2025-06-15T10:31:45Z"
  }
}
```

See research we made earlier on syntax for different agentic frameworks: .worktrees/rfc0/docs/rfc/agentic-signatures/asya-handler-syntax-comparisons.md

Asya: Regular flow for simple actors (no route/headers access):

```python
import asyncio

THRESHOLD = 0.75

async def flow(payload: dict) -> dict:  # compilable flow (actors are not compiled!!)
    # call and dynamically stream results
    async for event in actor1(payload):
        yield event  # yields upwards = to the caller or to the gateway
        if event["quality"] >= THRESHOLD:
            break  # need to send stop-signal to actor1
    # once actor1 loop finishes, calling sequentially:
    payload = await actor3(payload)
    payload = await actor4(payload)
    # calling in parallel - collecting results only to a sub-key, otherwise merging is unclear
    payload["sub_agents_results"] = await asyncio.gather(actor5_1(payload["agent1"]), actor5_2(payload["agent2"]))
    # if needed, later we can call a custom "merger" or "reducer" actor:
    payload = await actor5_reducer(payload)

    # loop:
    while payload["quality"] < THRESHOLD:
        payload = await actor6(payload)

    # custom exceptions:
    try:
        payload = await actor7(payload)
    except KeyError as e:
        # asya flow compiler will deploy actor7's sidecar with env vars instructing to send message
        # to the generated router in case of failure KeyError or its child classes (not yet implemented)
        logging.exception("Failed to do what actor7 is doing")  # will be executed in the generated router
        payload = await actor7_backup(payload)

async def actor1(payload: dict) -> dict:
    async for event in actor2(payload):
        event["actor1_seen"] = True
        yield event  # yield upstream
    await database_call()  # simple call
    payload = await actor3(payload)  # simple inline call! not an actor!

async def actor2(payload: dict) -> dict:
    yield {"partial": True, "text": "Hello"}
    yield {"partial": True, "text": " world!"}
    if payload["send_further"] == True:
        payload["actor2_processed"] = True
        yield payload  # non-partial event
```

Have I missed some useful syntax?


Now the hard part: how to enable these handlers reach headers/route and be able to modify them? (note: this information is usually static per one message: a sidecar receives a message, sends to asya_runtime.py via unix socket, which parses it, extracts payload and calls the handler with payload as argument.

My idea is to somehow utilize `yield`, for example:
```python
async def actor(payload: dict) -> dict:
    yield {**payload, "fan-out-index": 0}
    route = yield ".route"  # full jq syntax here. Alternatively, just "route" or "/route" like a command in Claude Code or Telegram
    route.insert(0, "new-next-actor")  # mutate route
    yield ".route", route  # asya_runtime.py receives this and updates in-memory route for all next payloads
    # next payloads will be sent to the new route
    yield {**payload, "fan-out-index": 1}
    yield {**payload, "fan-out-index": 2}
    yield {**payload, "fan-out-index": 3}
    # alternatively, we could send a single payload to a new route:
    yield {**payload, "foo": "bar"}, ".route", ["another-actor"] + route
```

what do you think of this syntax?
