## RFC: Flow DSL Free Variables and Iteration

> Extracted from epic 1c84.handler-signature-redesign. See also: 1ixt (message metadata vfs), 1ixz (typed handler signatures).

---

### 1. Overview / Problem Statement

The Asya flow compiler transforms Python flow definitions into networks of stateless router actors. Each actor call (`p = handler(p)` or `p = await handler(p)`) becomes a message boundary: the handler runs on a separate pod, and the router manipulates `route.actors` to dispatch messages between them. This is a form of Continuation-Passing Style (CPS) transformation.

The current compiler supports sequential calls, conditionals, while loops, try-except, early returns, break/continue, and payload mutations. However, three related capabilities remain unsupported:

1. **Free variables across actor boundaries.** A local variable assigned before an actor call and referenced after it will be silently lost, because the pre-call and post-call code execute in different router actors on potentially different pods. The compiler does not detect or prevent this today.

2. **For-loop support.** The parser explicitly rejects `for` loops with an error message directing users to use `while` loops instead. For loops introduce a loop variable that is inherently a free variable crossing the actor boundary inside the loop body.

3. **Async-for-yield streaming.** The `async for event in source: yield event` pattern -- consuming an async iterator from a sub-flow and re-yielding results -- requires iteration across actor boundaries and interacts with the CPS transformation in ways the compiler cannot currently handle.

All three concerns share a common prerequisite: the ability to detect and manage variables whose lifetimes span actor boundaries.

#### Current Compiler Architecture

The compiler pipeline consists of four stages:

```
Source (.py)  -->  Parser (AST)  -->  IR Operations  -->  Grouper  -->  Routers
                                                                          |
                                                                    +-----+-----+
                                                                    |           |
                                                                CodeGen     DotGen
                                                              (routers.py) (flow.dot)
```

**Parser** (`parser.py`): Walks the Python AST, produces IR operations. Accepts `def` and `async def` flow functions with a single dict parameter (`p`, `payload`, or `state`). Recognizes actor calls (`p = handler(p)` or `p = await handler(p)`), mutations (`p["key"] = val`), conditionals, while loops, try-except, break, continue, return, and class instantiations. Rejects `for` loops, standalone `yield`, standalone `await`, and bare expression statements.

**IR** (`ir.py`): Dataclass nodes -- `ActorCall`, `Mutation`, `Condition`, `WhileLoop`, `Break`, `Continue`, `TryExcept`, `ExceptHandler`, `Raise`, `Return`, `Convergence`.

**Grouper** (`grouper.py`): Transforms IR operations into `Router` objects. Each router is a generated envelope-mode handler that manipulates `route.actors` to insert the next steps. The grouper handles convergence (branches rejoining), loop back-edges, and try-except error routing.

**CodeGen** (`codegen.py`): Emits Python source code for each router, plus a `resolve()` function that maps handler names to actor names via `ASYA_HANDLER_*` environment variables.

The key invariant: **all state travels in the message payload**. Routers operate on `message['payload']` (aliased as `p`) and `message['route']`. There is no shared memory, no session state, no sticky routing.

---

### 2. Free Variable Analysis

#### 2.1 What Are Free Variables in the CPS Context

In the flow compiler, an **actor call** is a CPS split point. The code before the call becomes one router; the code after the call becomes a different router (or the continuation of a different actor). These run in separate processes, potentially on separate pods.

A **free variable** in this context is a local variable that is:
- **Defined** (assigned) before an actor call, AND
- **Referenced** (read) after that actor call

Such a variable exists in the scope of one router but is needed in the scope of the continuation. Since routers are separate actors, the variable's value is lost at the boundary.

```python
def flow(p: dict) -> dict:
    temp = p["items"][0]          # defined here
    p = handler_a(p)              # actor boundary -- new router starts after this
    p["first_item"] = temp        # referenced here -- ERROR: temp does not exist
    return p
```

The payload parameter `p` itself is NOT a free variable -- it is the message payload, automatically passed between actors by the sidecar. Only local variables (anything assigned to a name other than `p`/`payload`/`state`) can be free.

Class instance variables tracked by the parser (`self.instances`) are also not free variables -- they represent stateful handler classes instantiated once per actor, not per-message state.

#### 2.2 Detection Algorithm

The detection algorithm performs liveness analysis across actor call boundaries. For each router group produced by the grouper, the algorithm identifies variables that are live-in (needed but not defined within the group).

**Step 1: Identify actor call boundaries.**

Walk the IR operation list. Each `ActorCall` node is a boundary. The operations between consecutive boundaries form a "segment" that will execute within a single router.

**Step 2: Compute defined and referenced variables per segment.**

For each segment, extract:
- `DEF(segment)`: variables assigned in this segment (targets of `ast.Assign` and `ast.AugAssign` within `Mutation` nodes, plus class instantiations)
- `REF(segment)`: variables referenced in this segment (names loaded in `Mutation` code and `Condition` test expressions, excluding `p`, `payload`, `state`, and built-in names)

Use `ast.walk()` on the unparsed code strings to find `ast.Name` nodes with `ast.Load` context (references) and `ast.Store` context (definitions).

**Step 3: Propagate liveness backward.**

A variable `v` is a free variable crossing boundary `B_i` (the actor call between segment `i` and segment `i+1`) if:
- `v` is in `DEF(segment_j)` for some `j <= i`, AND
- `v` is in `REF(segment_k)` for some `k > i`, AND
- `v` is NOT in `DEF(segment_m)` for all `i < m <= k` (not redefined between the boundary and its use)

This is standard backward dataflow analysis for liveness:

```
LIVE_OUT(segment_i) = LIVE_IN(segment_{i+1})
LIVE_IN(segment_i)  = REF(segment_i) | (LIVE_OUT(segment_i) - DEF(segment_i))
FREE_VARS(B_i)      = LIVE_OUT(segment_i) & DEF_BEFORE(B_i)
```

where `DEF_BEFORE(B_i)` is the union of `DEF(segment_j)` for all `j <= i`.

**Handling control flow:** For conditionals, the analysis must consider all branches. A variable is live across a boundary if it is live on ANY path through the conditional. For while loops, the analysis iterates until a fixed point is reached (the loop body is analyzed as if it executes zero or more times).

#### 2.3 Phase 1: Compiler Error with Helpful Message

The initial implementation adds a validation pass after parsing and before grouping. When a free variable crossing an actor boundary is detected, the compiler emits a `FlowCompileError` with a message that tells the user exactly what to do:

```
FlowCompileError: Local variable 'temp' assigned at line 3 crosses actor boundary
at line 4 (handler_a call). The variable will be lost because handler_a runs in a
separate actor.

Fix: store it in the payload before the call and retrieve it after:

    p["__temp"] = temp          # before handler_a
    p = handler_a(p)
    temp = p.pop("__temp")      # after handler_a
```

**Implementation location:** New module `src/asya-cli/asya_cli/flow/analysis.py` containing a `FreeVariableAnalyzer` class. Called from `FlowCompiler.compile()` between `_parse()` and `_group()`.

**What to analyze:** The analysis operates on the flat IR operation list returned by the parser. It walks the list, tracking defined and referenced names in mutation code and condition test strings.

**Scope exclusions:**
- The payload parameter (`p`, `payload`, `state`) is excluded -- it flows automatically.
- Built-in names (`len`, `range`, `True`, `False`, `None`, etc.) are excluded.
- Class instance names tracked in `parser.instances` are excluded -- they are actor-level state, not message-level.
- Names imported at module level are excluded (though the flow DSL does not currently support imports).

#### 2.4 Phase 2: Auto-Serialization

Once detection is reliable, the compiler can automatically inject save/restore mutations around actor boundaries.

**Before the actor call,** for each free variable `v` crossing the boundary, insert:

```python
p["__local__v"] = v
```

**After the actor call** (at the start of the continuation segment), insert:

```python
v = p.pop("__local__v")
```

The `__local__` prefix is chosen to avoid collisions with user payload fields. The `pop()` call removes the temporary key after restoring, keeping the payload clean.

**Generated code example:**

```python
# User wrote:
def flow(p: dict) -> dict:
    temp = p["items"][0]
    p = handler_a(p)
    p["first_item"] = temp
    return p

# Compiler generates (in the pre-call router):
def router_flow_line_2_seq(message: dict) -> dict:
    p = message['payload']
    r = message['route']
    c = r['current']
    _next = []

    temp = p['items'][0]
    p['__local__temp'] = temp       # auto-injected save

    _next.append(resolve("handler_a"))
    _next.append(resolve("router_flow_line_4_seq"))

    r['actors'][c+1:c+1] = _next
    r['current'] = c + 1
    return message

# And in the post-call router:
def router_flow_line_4_seq(message: dict) -> dict:
    p = message['payload']
    r = message['route']
    c = r['current']
    _next = []

    temp = p.pop('__local__temp')   # auto-injected restore
    p['first_item'] = temp

    r['actors'][c+1:c+1] = _next
    r['current'] = c + 1
    return message
```

**Serialization constraints:**

Only JSON-serializable values can travel in the payload. The compiler cannot statically verify serializability in the general case, but it can:

1. Warn when the assigned expression is a function call with an unknown return type.
2. Error when the assigned expression is clearly non-serializable (e.g., `open()`, generator expressions, lambda).
3. For Phase 2 initial release, document that only JSON-serializable types (str, int, float, bool, list, dict, None) are supported. Non-serializable values will cause a runtime `TypeError` during JSON encoding.

**Implementation:** The `FreeVariableAnalyzer` gains a `serialize` mode (in addition to the existing `error` mode). In serialize mode, it returns a list of `(variable_name, boundary_index, def_lineno, ref_lineno)` tuples. The compiler inserts `Mutation` IR nodes at the appropriate positions before passing the operations to the grouper.

---

### 3. For-Loop Support

#### 3.1 Problem

The parser currently rejects `for` loops:

```python
# parser.py line 122-124
elif isinstance(stmt, ast.For):
    raise FlowCompileError(
        f"{self.filename}:{stmt.lineno}: 'for' loops are not supported. Use 'while' loops instead"
    )
```

For loops introduce two challenges:

1. **The loop variable is a free variable.** In `for item in items: p = await handler(p)`, the variable `item` is assigned by the for-loop iteration mechanism and used inside the loop body. If the body contains an actor call, `item` crosses the actor boundary.

2. **The iterator state must persist across actor boundaries.** The for-loop's position within the iterable (which element is "current") must survive the round-trip through the actor network.

```python
def flow(p: dict) -> dict:
    for item in p["items"]:       # 'item' is a free variable
        p["current"] = item
        p = process_item(p)       # actor boundary -- 'item' is lost
        p["results"].append(p["output"])  # needs 'item'? fine. needs iterator position? problem.
    return p
```

#### 3.2 Approach Options

**Option A: Compile-time unrolling (bounded for).**

For `for i in range(N)` where `N` is a literal integer, unroll into `N` sequential segments. Each iteration becomes a separate sequence of mutations and actor calls.

- Pros: Simple, no loop infrastructure needed, no free variable problem.
- Cons: Only works for statically-known bounds. Generates `O(N)` routers. Not suitable for `for item in p["items"]` where the iterable length is runtime-dependent.

**Option B: Compile to while + index variable.**

Transform the for-loop into a while-loop with an explicit index variable stored in the payload:

```python
# User writes:
for item in p["items"]:
    p["current"] = item
    p = process_item(p)

# Compiler transforms to:
p["__for_idx_0"] = 0
while p["__for_idx_0"] < len(p["items"]):
    item = p["items"][p["__for_idx_0"]]
    p["current"] = item
    p = process_item(p)
    p["__for_idx_0"] += 1
p.pop("__for_idx_0", None)
```

- Pros: Works for any iterable expressible as `p["key"]`. Reuses existing while-loop infrastructure (condition router, loop-back router). The index variable is in the payload, so it survives actor boundaries.
- Cons: The iterable expression must be indexable (list, not generator). The loop variable `item` is still a free variable if used after an actor call within the body -- requires auto-serialization from Phase 2.

**Option C: Sequential dispatch (pragmatic).**

Process one element per loop iteration via a dispatch router that checks the index and re-enters. Similar to Option B but with the iteration logic entirely in the generated router rather than transforming the AST.

- Pros: Clean separation between user code and iteration machinery.
- Cons: More complex router generation. Essentially the same as Option B at the router level.

#### 3.3 Recommended Approach

**Option B (compile to while + index)** is recommended because:

1. It reuses the existing `WhileLoop` IR node and all associated grouper/codegen infrastructure (condition routers, loop-back routers, break/continue handling, max iteration guards).
2. The transformation is a straightforward AST rewrite in the parser, before the IR is produced.
3. The index variable is stored in the payload (`p["__for_idx_N"]`), so it naturally survives actor boundaries.
4. The loop variable (`item` in the example) is handled by the free variable auto-serialization mechanism (Phase 2), which is needed anyway for other use cases.

**Transformation rules:**

| For-loop pattern | Transformation |
|---|---|
| `for item in p["key"]:` | `while __idx < len(p["key"]): item = p["key"][__idx]; ...; __idx += 1` |
| `for i in range(N):` | `while __idx < N: i = __idx; ...; __idx += 1` |
| `for i in range(A, B):` | `while __idx < B: i = __idx; ...; __idx += 1` (init `__idx = A`) |
| `for i in range(A, B, S):` | `while __idx < B: i = __idx; ...; __idx += S` (init `__idx = A`) |
| `for i, item in enumerate(p["key"]):` | Decompose into index + element access |

The `__for_idx_N` suffix `N` is a monotonically increasing counter to support nested for-loops.

**Implementation:**

1. In `parser.py`, replace the `FlowCompileError` for `ast.For` with a `_parse_for()` method.
2. `_parse_for()` performs the AST transformation from for-loop to while-loop + index.
3. The transformed while-loop is then processed by the existing `_parse_while()`.
4. A cleanup mutation (`p.pop("__for_idx_N", None)`) is appended after the loop.

**Dependency on free variable auto-serialization:** If the loop body contains an actor call and the loop variable is used after that call (within the same iteration), the loop variable is a free variable crossing an actor boundary. Phase 1 (error) will catch this. Phase 2 (auto-serialization) will handle it automatically. In the interim, users can manually save the loop variable to the payload before the actor call.

---

### 4. Async-For-Yield Streaming

#### 4.1 Pattern

The `async for ... yield` pattern is used for streaming composition -- a parent flow consumes events from a child flow and re-yields them (possibly transformed):

```python
async def parent_flow(p: dict):
    async for event in child_flow(p):
        event["source"] = "parent"
        yield event
```

This pattern is documented in the agentic flow compiler RFC (epic 1cnt, Section 5.4) and represents the primary mechanism for composing streaming actors.

#### 4.2 How the Compiler Handles Async Iteration

The `async for event in child_flow(p): yield event` construct involves two distinct mechanisms:

1. **The child flow call** (`child_flow(p)`) is an actor call. The child flow runs as a separate actor (or sub-network of actors) and produces events -- some partial (streaming), some non-partial (control).

2. **The iteration and yield** happen at the routing level, not the execution level. The parent does not literally iterate over the child's output in a Python loop. Instead:
   - The child actor's partial events are routed via `ASYA_PARTIAL_EVENTS_ROUTE` to either the gateway (identity passthrough) or a generated mutation router (transformation).
   - The child actor's non-partial (control) events follow the normal `route.actors` path to the next actor.

**Identity yield optimization:**

When the yield body contains no transformations (bare `yield event` or only non-await local operations), the compiler sets `ASYA_PARTIAL_EVENTS_ROUTE=""` on the child actor. Partial events stream directly to the gateway with zero intermediate hops.

**Mutation yield:**

When the yield body contains transformations (mutations, conditionals, awaits), the compiler generates a mutation router actor. The child actor's `ASYA_PARTIAL_EVENTS_ROUTE` is set to the mutation router's name. The mutation router applies the transformation and re-yields.

```python
# Compiler generates for the transformation case:
def parent_flow_yield_router(message: dict) -> dict:
    """Mutation router for parent_flow's yield body."""
    event = message['payload']
    event['source'] = 'parent'
    return message
```

#### 4.3 Interaction with CPS Transformation

The `async for ... yield` pattern interacts with CPS in several ways:

**Free variables in the yield body.** If the yield body references variables defined outside the `async for` block, those are free variables crossing the actor boundary between the parent flow's pre-iteration code and the mutation router:

```python
async def parent_flow(p: dict):
    prefix = "annotated"                    # defined here
    async for event in child_flow(p):
        event["tag"] = prefix               # free variable in mutation router
        yield event
```

The mutation router is a separate actor. The variable `prefix` must be serialized into the payload (or the event) before the child flow starts and restored in the mutation router. The auto-serialization mechanism from Section 2.4 handles this.

**Await in the yield body.** If the yield body contains an `await`, CPS splits the mutation router itself:

```python
async def parent_flow(p: dict):
    async for event in child_flow(p):
        event = await enrich(event)         # CPS split inside mutation router
        event["extra"] = event["id"]
        yield event
```

This creates a sub-network within the mutation router: the event goes to `enrich`, then to a continuation router that applies `event["extra"] = event["id"]` and re-yields. Free variables crossing this inner boundary (like `event` before and after the `await enrich` call) follow the same detection and serialization rules.

**Nested async-for-yield.** Flows that iterate over flows that iterate over flows create a chain of `ASYA_PARTIAL_EVENTS_ROUTE` settings. Each level either passes through (identity) or transforms (mutation router). The compiler handles this recursively -- each level's analysis is independent.

#### 4.4 New IR Node

A new IR node represents the `async for ... yield` construct:

```python
@dataclass
class AsyncForYield(IROperation):
    """async for event in source(p): ... yield event

    The source is an actor call. The body between 'async for' and 'yield'
    is a sequence of operations applied to each event.
    """
    source_name: str                    # Actor/function producing events
    iter_var: str                       # Loop variable name (e.g., "event")
    body: list[IROperation]             # Operations between async-for and yield
    is_identity: bool                   # True if body is empty or trivial
```

The parser detects the `async for ... yield` pattern and produces this node. The grouper generates the appropriate routing configuration (identity passthrough or mutation router).

---

### 5. Implementation Phases

#### Phase 1: Free Variable Detection (Error Mode)

**Goal:** Detect free variables crossing actor boundaries and emit compiler errors with helpful fix suggestions.

**Deliverables:**
- `src/asya-cli/asya_cli/flow/analysis.py` -- `FreeVariableAnalyzer` class
- Integration into `FlowCompiler.compile()` pipeline (between parse and group)
- Unit tests for detection across linear, conditional, and loop boundaries
- Error message includes the variable name, definition line, boundary line, and a code suggestion

**No changes to:** parser, grouper, codegen, IR nodes.

**Estimated scope:** ~200 lines of analysis code, ~300 lines of tests.

#### Phase 2: Free Variable Auto-Serialization

**Goal:** Automatically inject save/restore mutations for free variables crossing actor boundaries.

**Deliverables:**
- Extend `FreeVariableAnalyzer` with `serialize` mode
- Inject `Mutation` IR nodes for save (`p["__local__v"] = v`) and restore (`v = p.pop("__local__v")`)
- Compiler flag or config to choose between error mode and auto-serialize mode
- Unit tests for serialization correctness across all boundary types
- Documentation of serialization constraints (JSON-serializable types only)

**Depends on:** Phase 1 (detection must be correct before auto-serialization is safe).

#### Phase 3: For-Loop Support

**Goal:** Extend the parser to accept `for` loops by transforming them into while loops with an index variable.

**Deliverables:**
- `_parse_for()` method in `FlowParser`
- AST transformation: for-loop to while-loop + index
- Cleanup mutation for index variable after loop exits
- Support for `range()` patterns (with literal and expression bounds)
- Support for iterable patterns (`for item in p["key"]`)
- Unit tests for all for-loop patterns
- Update `AGENTS.md` to remove "Loops (for, while) not yet supported" limitation note

**Depends on:** Phase 2 (loop variables that cross actor boundaries within the loop body need auto-serialization). Phase 1 (error mode) is sufficient for for-loops where the loop variable is NOT used after an actor call within the body.

#### Phase 4: Async-For-Yield Streaming

**Goal:** Support the `async for event in source: yield event` pattern for streaming composition.

**Deliverables:**
- `AsyncForYield` IR node
- Parser detection of the `async for ... yield` pattern
- Grouper: identity yield optimization (set `ASYA_PARTIAL_EVENTS_ROUTE=""`)
- Grouper: mutation router generation for non-identity yield bodies
- CodeGen: mutation router code generation
- DotGen: visualization of streaming composition edges
- Unit tests for identity passthrough, mutation yield, nested composition, and free variables in yield bodies

**Depends on:** Phase 2 (free variables in yield bodies need auto-serialization). Also depends on runtime and sidecar support for multi-frame streaming protocol and `ASYA_PARTIAL_EVENTS_ROUTE` routing (from epic 1cnt, agentic flow compiler).

---

### 6. Dependencies

| Dependency | Epic | Relationship |
|---|---|---|
| Agentic flow compiler | 1cnt | Provides the CPS transformation infrastructure, `AwaitCall` IR node, async flow function support, and streaming protocol. Phases 1-3 of this RFC can proceed independently for sync flows. Phase 4 requires 1cnt's streaming support. |
| Message metadata VFS | 1ixt | Independent. Free variable analysis does not interact with `/tmp/msg/` filesystem access. |
| Typed handler signatures | 1ixz | Independent but complementary. Type annotations on handler parameters could improve serialization constraint checking (Phase 2). |
| While-loop infrastructure | (existing) | For-loop support (Phase 3) reuses `WhileLoop` IR node, condition routers, loop-back routers, and max iteration guards already implemented in the grouper. |

---

### 7. Open Questions

1. **Serialization boundary.** Should the compiler attempt to verify JSON-serializability at compile time, or defer all checking to runtime? Compile-time checking is incomplete (cannot trace through function calls) but could catch obvious cases (assigning `open()` result to a variable).

2. **Namespace for auto-serialized keys.** The `__local__` prefix is proposed. Should it be configurable? Should it include the flow name to avoid collisions when flows are composed (one flow's serialized variables could collide with another's)?

3. **For-loop over non-indexable iterables.** `for item in p["items"]` works when `p["items"]` is a list (indexable). What about `for k, v in p["data"].items()`? The while+index transformation does not apply to dict iteration. Options: reject with error, transform to `list(p["data"].items())` + index, or support only list iteration initially.

4. **Max iteration guard for for-loops.** While-loops have `_ASYA_MAX_LOOP_ITERATIONS` as a safety guard. For-loops are bounded by the iterable length, so they do not need this guard in principle. However, a very large iterable could still cause runaway routing. Should the guard be applied to for-loops as well?

5. **Opt-in vs opt-out for auto-serialization.** Should auto-serialization be the default (Phase 2 replaces Phase 1), or should it remain opt-in via a compiler flag? The argument for opt-in: auto-serialization adds payload size and may surprise users who expect the compiler to force explicit state management.
