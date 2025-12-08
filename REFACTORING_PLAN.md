# Flow → Scene IR Refactoring Plan

## Overview

Complete refactoring to:
1. Rename `flow` → `scene` (new terminology: actor → scene → play)
2. Transform IR to use goto-based primitives (Label, ConditionalGoto, Goto)
3. Two-level hierarchy: Scene steps (ActorCall | Router) and Router operations (mutations + gotos + ActorCalls)

## Terminology Changes

### Old → New
- `flow` → `scene` (partial interconnection of actors)
- `FlowIR` → `SceneIR`
- `FlowParser` → `SceneParser`
- `flow_cli.py` → `scene_cli.py`
- `flow/` directory → `scene/`
- `flow_*.py` → `scene_*.py` (Python scene files)
- `asya flow compile` → `asya scene compile`

### Concepts
- **Actor**: Individual handler function
- **Scene**: Partial interconnection of actors (compiled from Python DSL)
- **Play**: Complete interconnection formed from connected scenes or individual actors

## Phase 1: Rename Flow → Scene

### Files to rename/update:
- [ ] `src/asya-cli/asya_cli/flow/` → `src/asya-cli/asya_cli/scene/`
- [ ] `src/asya-cli/asya_cli/flow_cli.py` → `src/asya-cli/asya_cli/scene_cli.py`
- [ ] All imports: `from asya_cli.flow` → `from asya_cli.scene`
- [ ] All class names: `FlowIR` → `SceneIR`, `FlowParser` → `SceneParser`, etc.
- [ ] All docstrings and comments mentioning "flow"
- [ ] Example files: `examples/flows/` → `examples/scenes/`
- [ ] CLI command: `asya flow` → `asya scene`

### Impact analysis:
- Main CLI entry point: `asya_cli/cli.py`
- Scene CLI: `asya_cli/scene_cli.py`
- All scene module files: `parser.py`, `compiler.py`, `analyzer.py`, `generator.py`, `diagram.py`, `emitter.py`, `errors.py`, `ir.py`

## Phase 2: Update IR Structure

### Current IR (ir.py)
Already updated with:
- ✅ `SceneIR.steps` instead of `operations`
- ✅ Two-level hierarchy
- ✅ Router operations: `PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall`

### New IR nodes:
- `ActorCall`: Call an actor (can appear in steps or inside router)
- `Router`: Non-recursive router with flat operations
- `PayloadMutation`: Mutate payload
- `ClassInstantiation`: Instantiate helper class
- `Label`: Goto target
- `ConditionalGoto`: if condition goto true_target else goto false_target
- `Goto`: Unconditional jump

### Removed IR nodes:
- ❌ `HandlerCall` → replaced by `ActorCall`
- ❌ `Assignment` → replaced by `PayloadMutation`
- ❌ `IfBlock` → replaced by `Router` with `ConditionalGoto`
- ❌ `WhileLoop` → replaced by `Router` with `Label`/`Goto`
- ❌ `Break` → replaced by `Goto` to loop exit label
- ❌ `Continue` → replaced by `Goto` to loop start label
- ❌ `Return` → removed (implicit at scene end)

## Phase 3: Parser Rewrite (parser.py)

### Current structure:
- `SceneParser._parse_function_body()` → parses statements
- Returns list of old IR operations

### New structure:
Transform Python AST to new IR with Label/Goto primitives.

### Transformation rules:

#### 1. Simple statements
```python
# Python
p = handler(p)
p["key"] = value
var = ClassName(args)

# IR
ActorCall(qualified_name, display_name)  # At scene level
PayloadMutation(key, value_str, value_ast)  # Inside router
ClassInstantiation(...)  # Inside router
```

#### 2. If/elif/else
```python
# Python
if cond_a:
    ops_a
elif cond_b:
    ops_b
else:
    ops_c

# IR (inside Router)
ConditionalGoto(cond_a, ..., "branch_a", "check_b")
Label("branch_a")
<ops_a>
Goto("after_if")

Label("check_b")
ConditionalGoto(cond_b, ..., "branch_b", "branch_else")
Label("branch_b")
<ops_b>
Goto("after_if")

Label("branch_else")
<ops_c>
Label("after_if")
```

#### 3. While loop
```python
# Python
while condition:
    body

# IR (inside Router)
Label("loop_start")
ConditionalGoto(condition, ..., "loop_body", "loop_exit")
Label("loop_body")
<body>
Goto("loop_start")
Label("loop_exit")
```

#### 4. Break/Continue
```python
# Python break
break

# IR
Goto("loop_exit")  # Jump to loop's exit label
```

```python
# Python continue
continue

# IR
Goto("loop_start")  # Jump to loop's start label
```

### Router grouping algorithm:

**Rule**: Create a Router when encountering control flow (if/while) or payload mutations not at scene level.

**Example**:
```python
def scene_example(p):
    p = init(p)        # Scene level ActorCall

    p["x"] = 0         # Start Router here (mutation)
    if p["x"] < 10:    # Control flow
        p = process(p)

    p = final(p)       # End Router, scene level ActorCall
```

**IR**:
```
SceneIR.steps = [
    ActorCall("init"),
    Router(operations=[
        PayloadMutation("x", "0"),
        ConditionalGoto("p['x'] < 10", ..., "then", "after"),
        Label("then"),
        ActorCall("process"),
        Label("after"),
    ]),
    ActorCall("final"),
]
```

### Implementation tasks:

- [ ] Add `_label_counter` to parser for unique label generation
- [ ] Implement `_parse_if_to_router()` - transform if/elif/else to ConditionalGoto/Label/Goto
- [ ] Implement `_parse_while_to_router()` - transform while to Label/ConditionalGoto/Goto
- [ ] Implement `_parse_break()` - emit Goto to loop exit (track loop context)
- [ ] Implement `_parse_continue()` - emit Goto to loop start
- [ ] Implement router grouping - detect when to start/end Router
- [ ] Update `_parse_handler_call()` → `_parse_actor_call()`
- [ ] Update `_parse_payload_mutation()` - emit PayloadMutation
- [ ] Track loop context stack for break/continue target labels

## Phase 4: Analyzer Simplification (analyzer.py)

### Current analyzer:
- Assigns router IDs to IfBlock/WhileLoop
- Analyzes control flow
- Sets continuation operations

### New analyzer (much simpler):
The IR is already flat and explicit - may not need analyzer at all!

**Possible tasks**:
- [ ] Validate label references (every Goto has matching Label)
- [ ] Validate no Router inside Router
- [ ] Compute router metadata (for documentation)
- [ ] Or **remove entirely** if not needed

## Phase 5: Generator Rewrite (generator.py)

### Current generator:
- Generates router functions from IfBlock/WhileLoop
- Collects actors from operations
- Handles nesting

### New generator:
Generate router code from flat Router.operations with Label/ConditionalGoto/Goto.

### Code generation rules:

#### Router function template:
```python
def router_id(envelope: dict) -> dict:
    """Router docstring"""
    p = envelope['payload']
    r = envelope['route']
    c = r['current']

    <operations>

    return envelope
```

#### Operation code generation:

**PayloadMutation**:
```python
p["key"] = value_str
```

**ClassInstantiation**:
```python
var_name = ClassName(args, kwargs)
```

**Label**:
```python
# Label: label_name
```

**ConditionalGoto**:
```python
if condition_str:
    goto_code_for_true_target
else:
    goto_code_for_false_target
```

**Goto**:
Generates route manipulation to jump to target label's continuation.

**ActorCall (inside router)**:
```python
r['actors'][c+1:c+1] = [resolve("qualified_name")]
```

### Label resolution strategy:

Use label-to-block mapping to generate structured Python code from goto graph.

**Algorithm**:
1. Build control flow graph from Label/Goto operations
2. Detect structured control flow (if/while patterns)
3. Generate nested Python if/else/while from CFG
4. Fall back to goto simulation if needed

### Implementation tasks:

- [ ] Implement `_generate_router_function()` - main router code generation
- [ ] Implement `_generate_operation()` - dispatch operation code generation
- [ ] Implement CFG analysis for label resolution
- [ ] Generate structured Python from gotos (detect if/while patterns)
- [ ] Handle ActorCall inside router (add to route)
- [ ] Remove old IfBlock/WhileLoop generation code

## Phase 6: Diagram Update (diagram.py)

### Current diagram:
- Visualizes IfBlock/WhileLoop as clusters
- Shows branching with colored edges

### New diagram:
Visualize Router operations with explicit control flow.

### Visualization approach:

**Option A**: Show labels and gotos explicitly
- Nodes: ActorCall, Router (cluster), Label (diamond), Operations (boxes)
- Edges: Goto (blue), ConditionalGoto true/false (green/red)

**Option B**: Reconstruct high-level structure
- Detect if/while patterns from goto graph
- Show structured control flow like current diagrams

**Recommended**: Option B - maintain current visual style but generate from new IR.

### Implementation tasks:

- [ ] Update imports to use new IR nodes
- [ ] Implement `_process_router()` - visualize Router as cluster
- [ ] Implement goto-to-structure detection
- [ ] Update edge coloring for ConditionalGoto
- [ ] Remove old IfBlock/WhileLoop visualization
- [ ] Test diagram generation on examples

## Phase 7: Emitter Update (emitter.py)

### Current emitter:
- Emits entrypoint router
- Emits if/while routers
- Uses templates

### New emitter:
Emit routers from Router IR nodes.

### Implementation tasks:

- [ ] Update router collection to iterate SceneIR.steps
- [ ] Generate router functions from Router.operations
- [ ] Update environment variable generation
- [ ] Update templates for new terminology (scene, not flow)
- [ ] Test generated code

## Phase 8: Testing

### Test files to update:
- [ ] `src/asya-cli/tests/` - update all scene tests
- [ ] `examples/scenes/` - rename and verify compilation

### Test strategy:
1. **Unit tests**: Test parser transformations for each Python construct
2. **Integration tests**: Compile example scenes, verify generated code
3. **Diagram tests**: Verify diagram generation
4. **End-to-end**: Compile, deploy, execute real scenes

### Example scenes to test:
- [ ] `conditional_scene.py` - if/elif/else
- [ ] `loop_scene.py` - while with break/continue
- [ ] `complex_scene.py` - nested control flow
- [ ] `simple_scene.py` - just actor calls

## Phase 9: Documentation

- [ ] Update CLAUDE.md with new terminology
- [ ] Update README files
- [ ] Add transformation examples to docs
- [ ] Document IR structure

## Implementation Order

### Step-by-step execution:

1. ✅ **Phase 2 complete** - IR structure updated
2. **Phase 1**: Rename flow → scene (files, imports, classes)
3. **Phase 3**: Rewrite parser to emit new IR
4. **Phase 5**: Rewrite generator to generate from new IR
5. **Phase 6**: Update diagram visualization
6. **Phase 7**: Update emitter
7. **Phase 4**: Simplify/remove analyzer (if not needed)
8. **Phase 8**: Test on examples
9. **Phase 9**: Update documentation

### Expected breakage:
- Everything will break after Phase 1 (rename)
- Parser will emit new IR after Phase 3
- Code generation will work after Phase 5
- Full pipeline works after Phase 7

### Rollback strategy:
Git commit after each phase for easy rollback if needed.

## Estimated Complexity

- **Phase 1** (rename): 2-3 hours - mechanical refactoring
- **Phase 3** (parser): 4-6 hours - complex transformation logic
- **Phase 5** (generator): 3-4 hours - CFG analysis and code generation
- **Phase 6** (diagram): 2-3 hours - visualization update
- **Phase 7** (emitter): 1-2 hours - template updates
- **Phase 8** (testing): 2-3 hours - verification and fixes

**Total**: 14-21 hours of focused work

## Success Criteria

- [ ] All scenes compile without errors
- [ ] Generated router code matches expected structure
- [ ] Diagrams visualize control flow correctly
- [ ] Example scenes execute correctly
- [ ] All tests pass
- [ ] Documentation updated
