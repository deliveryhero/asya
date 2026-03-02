---
title: Allow compiler to dive into functions
priority: 2
type: task
---

We want to give users means to develop flows smartly by grouping repeated code in functions. Example:
```py
async def flow(state):
    ...
    
    ...
```
this could be grouped into:
```py
async def call_tools_subflow(state):
    if state.get("subtask") == "sql":
        state = await sql_specialist(state)
    elif state.get("subtask") == "api":
        state = await api_specialist(state)
    else:
        state = await data_generalist(state)
    return state

async def flow(state):
    ...
    state = await call_tools_subflow(state)
    ...
```

For that, compiler must know which functions are actors and flows.

However, asya doesn't provide any pip package to mark handlers with `@actor` or `@flow`. Also, actor handler is a business logic, it can be deployed as actors of different names simultaneously (name is a deployment, infra-level info, not business logic), so we cannot pass actor names in actor-level code.

I'd save this information for now in the flow file:
```py
async def flow(state):
    """
    actors-and-flows:
    - sql_specialist -> actor-name-sql-specialist-1
    - sql_specialist -> api-specialist
    ...
    """
    ...
```
help me define the best format for flow docstr to keep mapping handler -> actor/flow name.

Note: we're encouraging users to write helper methods for local testing (see .aint/epics/.closed/1l01.abi-instead-vfs/abi-protocol.md - an actor may yield multiple ABI control events. But as long as it yields exactly one non-control dict, it can be turned into a coroutine). I'm thinking we could somehow mark such functions/decorators and teach asya flow compiler not to dive into them. Or more generically: an explicit docstr or inline comment NOT to dive into a function call.

```py
async def actor(gen):  # by name - we don't decompile
    events = [e async for e in gen if not isinstance(e, tuple)]
    if len(events) != 1:
        raise ValueError(f"Expected 1 yield, got {len(events)}")
    return events[0]  # turn yield to return

async def flow(state):  # <- flow must be SIMPLE, only awaits! all async for logic is inside actors!
    state = await actor(llm(state))
    state = await actor(validator(state))


# or as decorator:
def actor(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)
        events = [e async for e in gen if not isinstance(e, tuple)]
        return events[0]
    return wrapper

@actor
async def llm(state):
    # yield ...
    ...

# and then - linear code that works locally. When deployed, sidecar will call bare function llm.__wrapped__
async def flow(state):
    state = await llm(state)
    state = await validator(state)
```

Also, we don't have a way to mark the flow function as flow - its signature is exactly same as actor.