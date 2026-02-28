to do typed partial signatures - add small wrapper/adapter instaed of env vars:
1. map inputs/outputs to state
2. type checking, validation
```py
async def user_function(foo: Foo, bar: Bar):
    # tool or whatever DS need to write
    return {"baz": 123}

async def actor_adapter1(state):
    # adapter to protocol: dict -> dict
    foo = Foo(state["foo"])
    bar = Bar(state["bar"])
    state["result"] = user_function(foo, bar)
    return state

async def actor_adapter2(state):
    foo = Foo(state["key"]["subkey"]["foo"])
    bar = Bar(state["key"]["bar"])
    state["result"] = user_function(foo, bar)
    return state
```


```python
async def actor_gen(state):
    yield "FLY", {"partial": True, ...} # streaming event - need to replace VFS with yield "SET"/"GET"
    prev_route = yield "GET", ".route.prev"
    if "zoo" in prev_route:
        # set new next immediate route
        yield "SET", ".route.next[:0]", ["new-immediate-next"]

    yield {"foo": ...} # regular event, fan-out (index 1)
    yield {"bar": ...} # regular event, fan-out (index 2)
    state["done"] = True  # just mutate? similar to ctx of adk
    yield state
```

ADK - everyone yields a small `Event`
Asya - everyone (every actor) ONLY communicates via full `State`, which might contain multiple events. If actor needs an action in between - split it into two actors.
```python
async def llm(state):
    yield 'FLY', {"foo": "bar"} # streaming
    yield 'FLY', {"foo": "bar"} # streaming
    yield 'FLY', {"foo": "bar"} # streaming
    
    event = {"tool_call": 123}
    if "events" not in state:
        state["events"] = []
    state["events"].append(event)
    yield state
```

TODO: Neex to env var protection: max num of fanout (for agents in the flow - max should be 1, otherwise flow protocol 1-1 breaks and message duplicates, data flow breaks).

Then - we'll define a slim helper to filter out all ABI yields (control yields) and ensure each function yields exactly one payload (no fan-out):
```python
async def actor(gen):  # by name - we don't decompile
    events = [e async for e in gen if not isinstance(e, tuple)]
    if len(events) != 1:
        raise ValueError(f"Expected 1 yield, got {len(events)}")
    return events[0]  # turn yield to return

async def flow(state):  # <- flow must be SIMPLE, only awaits! all async for logic is inside actors!
    state = await actor(llm(state))
    state = await actor(validator(state))


# or as decorator:
def actor_handler(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)
        events = [e async for e in gen if not isinstance(e, tuple)]
        return events[0]
    return wrapper

@actor_handler
async def llm(state):
    # yield ...
    ...

# and then - linear code that works locally. When deployed, sidecar will call bare function llm.__wrapped__
async def flow(state):
    state = await llm(state)
    state = await validator(state)

#sidecar should probably unwrap functions anyways from all decorators (except the ones explicitly defined, if needed in the future) using inspect.unwrap or manually:
# def get_original(func):
#     while hasattr(func, "__wrapped__"):
#         func = func.__wrapped__
#     return func
```


async generators adapters:
```py
async def actor_gen(state):
    yield {...} # streaming
    yield {...} # partial fan-out (index 1)
    yield {...} # partial fan-out (index 2)
    state["done"] = True
    yield state  # last, not first, should be main one - can we do it if no batching on sidcar?

# Or real example: https://medium.com/@d3xvn/exploring-googles-agent-development-kit-adk-71a27a609920
class CheckerAgent(BaseAgent):
    """Agent that checks if the guessed number is correct."""
    def __init__(self, name: str):
        super().__init__(name=name)

    async def _run_async_impl(self, context):
        # pull the last guess out of state
        last = context.session.state.get("last_response", "")
        # keep looping until we actually saw "42"
        found = "42" in last
        # "continue" vs "stop" is your protocol
        verdict = "stop" if found else "continue"
        # ALWAYS supply an EventActions instance (cannot be None)
        actions = EventActions(escalate=found)
        yield Event(
            author=self.name,
            content=types.Content(
                role="assistant",
                parts=[types.Part(text=verdict)]
            ),
            actions=actions
        )


class CheckerAgent_Actor:
    def __init__(self, agent: CheckerAgent):
        self._agent = agent
        
    @actor_handler
    async def gen_adapter(state):  #<-- take adk agent, wrap it to use on asya
        foo = Foo(state["foo"])
        bar = Bar(state["bar"])
        
        # batch here
        state["events"] = state.get("events", [])
        async for event in self._agent._run_async_impl(...):  #<- calls actor here
            ...
            state["events"].append(event)
            if event.is_large_media_file():
                write_media_file(...)
        
        yield state  # single yield

async def flow(state):
    checker = CheckerAgent_Actor(...)
    state = await checker.gen_adapter(state)  # turns yield to await
    ...
```


flow: use only await. Allow functional programming tools like comprehensions

for fan-in:
```python
async def flow(state):
    state["events"].extend(x async for x in fanout_actor(state))
```








agentic asya needs only very basic classes:
- Agent ([LlmAgent](https://github.com/google/adk-python/blob/main/src/google/adk/agents/llm_agent.py#L185)):
  - model
  - instructions
  - available tools (metadata)
  - ...

- [AgentTool](https://github.com/google/adk-python/blob/8ddddc040ca10c75eca6752154773862069d9a1a/src/google/adk/tools/agent_tool.py#L92)
  - run_async

maybe some more (see docs; see [gh search](https://github.com/search?q=repo%3Agoogle%2Fadk-python+%22class+agent%22+&type=code))

Rest (tool calling, sub agents calling, workflows - [SequentialAgent](https://google.github.io/adk-docs/agents/workflow-agents/sequential-agents/#full-example-code-development-pipeline) etc) is a custom or pre-built `flow`.
