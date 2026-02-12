# Asya Flow Compiler

The Asya Flow DSL compiler transforms Python-based workflow descriptions into router-based actor networks.

## Overview

**Purpose**: Simplify complex actor pipeline development by writing Python-like flow definitions instead of manually configuring routes and actors.

**Key Benefits**:
- Write actor pipelines in familiar Python syntax
- Automatic router generation and optimization
- Compile-time validation of flow logic
- Visual flow diagrams with Graphviz integration

## Architecture

```
┌────────────────┐
│   Flow DSL     │  Python function with p: dict parameter
│  (user code)   │  Contains handler calls, conditionals, mutations
└────────────────┘
         │
         ▼
┌─────────────────┐
│     Parser      │  Parse Python AST, extract operations
│  (FlowParser)   │  Validate flow structure
└─────────────────┘
         │
         ▼
┌───────────────────┐
│    Grouper        │  Group operations into routers
│ (OperationGrouper)│  Optimize mutation batching
└───────────────────┘
         │
         ▼
┌─────────────────┐
│   Code Gen      │  Generate router Python code
│ (CodeGenerator) │  Create resolve() function
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  Routers (.py)  │  Deployable actor code
│  + Plot (.dot)  │  Optional visualization
└─────────────────┘
```

## Flow DSL Syntax

### Function Signature

Every flow must have exactly one function with this signature:

```python
def <flow_name>(p: dict) -> dict:
    # Flow body
    return p
```

**Requirements**:
- Parameter name: `p` or `payload`
- Parameter type: `dict`
- Return type: `dict`
- Must have exactly one parameter

### Supported Operations

#### 1. Actor Calls

Call actors/handlers to process payload:

```python
def my_flow(p: dict) -> dict:
    # Function handlers - simple stateless operations
    p = validate_input(p)
    p = normalize_data(p)

    # Class-based handlers - stateful operations (model loading, config)
    model = MLModel()  # Instantiate once (only default args)

    # Use instantiated classes
    p = preprocessor.clean(p)
    p = model.predict(p)

    return p


# Class definitions with default arguments
class MLModel:
    def __init__(self, model_path: str = "/models/default"):
        # Load model once at initialization
        self.model = load_model(model_path)

    def predict(self, p: dict) -> dict:
        """Run prediction."""
        result = self.model.predict(p["input"])
        return {**p, "prediction": result}
```

**Rules**:
- Actor calls must pass `p` as the only argument
- Result must be assigned back to `p`
- Class instantiation must use **only default arguments** (no positional args, no keyword args)
- Instance variables can be used for method calls
- Use classes for stateful handlers (model loading, configuration)
- Use functions for simple stateless handlers

#### 2. Payload Mutations

Modify payload fields inline:

```python
def my_flow(p: dict) -> dict:
    p["status"] = "processing"      # Assignment
    p["count"] += 1                  # Augmented assignment
    p["nested"]["key"] = "value"    # Nested subscripts
    return p
```

**Supported**:
- Subscript assignment: `p["key"] = value`
- Nested subscripts: `p["a"]["b"]["c"] = value`
- Augmented assignment: `p["x"] += 1`, `p["y"] *= 2`
- Expressions: `p["result"] = p["x"] + p["y"] * 2`

#### 3. Conditionals

Branch execution based on conditions:

```python
def my_flow(p: dict) -> dict:
    if p["type"] == "A":
        p = handler_a(p)
    elif p["type"] == "B":
        p = handler_b(p)
    else:
        p = handler_default(p)
    return p
```

**Supported**:
- `if`/`elif`/`else` statements
- Nested conditionals
- Empty branches (with `pass`)
- Complex boolean expressions
- Early returns

#### 4. Early Returns

Exit flow early based on conditions:

```python
def my_flow(p: dict) -> dict:
    if p.get("skip", False):
        return p  # Skip processing

    p = handler(p)
    return p
```

### Complete Example

```python
def order_processing_flow(p: dict) -> dict:
    # Initialize
    p["status"] = "received"
    p["timestamp"] = time.time()

    # Validate
    p = validate_order(p)

    # Conditional processing
    if not p.get("valid", False):
        p["status"] = "rejected"
        return p  # early return

    # Process by type
    if p["order_type"] == "express":
        p["priority"] = "high"
        p = express_handler(p)
    elif p["order_type"] == "standard":
        p["priority"] = "normal"
        p = standard_handler(p)
    else:
        p["priority"] = "low"
        p = bulk_handler(p)

    # Finalize
    p = payment_processor(p)
    p["status"] = "completed"

    return p
```

## Compilation Process

### 1. Parsing Phase

**Input**: Python source code
**Output**: List of IR operations

The parser:
- Validates flow function signature
- Extracts operations from AST
- Preserves line numbers for debugging
- Detects syntax errors and invalid patterns

**IR Operations**:
- `ActorCall(lineno, name)` - Actor invocation
- `Mutation(lineno, code)` - Payload modification
- `Condition(lineno, test, true_branch, false_branch)` - Conditional logic
- `Return(lineno)` - Flow exit

### 2. Grouping Phase

**Input**: List of IR operations
**Output**: List of routers

The grouper:
- Creates `start_<flow>` and `end_<flow>` routers
- Groups consecutive mutations into single routers
- Converts conditionals into routers with branching
- Optimizes router count by batching operations

**Router Types**:
- **Start Router**: Entry point, contains initial mutations and first actors
- **Mutation Router**: Executes payload mutations, routes to next actors
- **Conditional Router**: Evaluates condition, routes to true/false branches
- **End Router**: Exit point, marks flow completion

### 3. Code Generation Phase

**Input**: List of routers
**Output**: Python code

The generator produces:
- Router function definitions
- `resolve()` function for handler-to-actor mapping
- Environment variable documentation
- Kubernetes deployment examples

**Generated Code Structure**:

```python
# Header with metadata
"""
Auto-generated by asya flow compiler
Source: my_flow.py
Generated: 2025-12-13 12:00:00
"""

# Environment variables documentation
"""
Set these environment variables:
ASYA_HANDLER_HANDLER_A="my_module.handler_a"
ASYA_HANDLER_HANDLER_B="my_module.handler_b"
"""

# Router functions
def start_my_flow(envelope: dict) -> dict:
    """Entrypoint for flow 'my_flow'"""
    r = envelope['route']
    c = r['current']

    # Mutations
    p = envelope['payload']
    p["status"] = "processing"
    envelope['payload'] = p

    # Routing
    r['actors'][c+1:c+1] = [resolve("handler_a"), resolve("handler_b")]
    return envelope

def router_my_flow_line_10_if(envelope: dict) -> dict:
    """Router at line 10"""
    r = envelope['route']
    c = r['current']
    p = envelope['payload']

    _next = []
    if p["condition"]:
        _next.append(resolve("handler_true"))
    else:
        _next.append(resolve("handler_false"))

    r['actors'][c+1:c+1] = _next
    return envelope

def end_my_flow(envelope: dict) -> dict:
    """Exitpoint for flow 'my_flow'"""
    return envelope

# Handler resolution
def resolve(handler_full_name: str) -> str:
    """Resolve handler to actor name via environment variables"""
    # ... implementation ...
```

## CLI Usage

### Compile Flow

```bash
asya flow compile <flow.py> --output <output-dir>
```

**Generates**:
- `routers.py` - Router implementations
- `flow.dot` - Graphviz diagram (if graphviz installed)
- `flow.png` - Visual flow diagram (if graphviz installed)

### Validate Flow

```bash
asya flow validate <flow.py>
```

Checks flow syntax without generating code.

## Deployment

### 1. Write Flow

```python
# my_flow.py
def my_flow(p: dict) -> dict:
    p = preprocess(p)
    p = model_predict(p)
    p = postprocess(p)
    return p

def preprocess(p: dict) -> dict:
    return p

def model_predict(p: dict) -> dict:
    return p

def postprocess(p: dict) -> dict:
    return p
```

### 2. Compile

```bash
asya flow compile my_flow.py --output compiled/
```

### 3. Deploy Routers as Actors

Each generated router becomes an AsyncActor:

```yaml
# routers.yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: start-my-flow
spec:
  image: my-routers:latest
  transport: rabbitmq
  handler: compiled_routers.start_my_flow
  env:
    - name: ASYA_HANDLER_PREPROCESS
      value: "my_module.preprocess"
    - name: ASYA_HANDLER_MODEL_PREDICT
      value: "my_module.model_predict"
    - name: ASYA_HANDLER_POSTPROCESS
      value: "my_module.postprocess"
```

### 4. Deploy Handler Actors

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: preprocess
spec:
  image: my-handlers:latest
  transport: rabbitmq
  handler: my_module.preprocess
```

## Visualization

Flow compiler generates Graphviz diagrams:

```
┌────────────────┐=
│  start_my_flow   │  (lightgreen)
│  =============   │
│  p["status"] =   │
│    "processing"  │
└────┘
         │
         ▼
┌────────────────┐=
│    preprocess    │  (lightblue)
└────┘
         │
         ▼
┌────────────────┐=
│  router_line_5   │  (wheat)
│  ==============  │
│  if p["valid"]   │
│  ┌=======,=======│
│  │ TRUE  │FALSE ││
└────┘│
└────┘
       │       │
       ▼       ▼
   handler_a handler_b
       │       │
       └────┘
           ▼
   ┌================
   │  end_my_flow  │  (lightgreen)
   └────┘
```

**Colors**:
- Green: Start/End routers
- Wheat: Conditional routers
- Blue: User actors
- Yellow: Condition boxes

## Optimization Strategies

### Mutation Batching

Consecutive mutations are grouped into single router:

```python
# Source
p["a"] = 1
p["b"] = 2
p["c"] = 3
p = handler(p)

# Generates single router with all mutations
def router_mutations(envelope: dict) -> dict:
    p = envelope['payload']
    p["a"] = 1
    p["b"] = 2
    p["c"] = 3
    envelope['payload'] = p
    r['actors'][c+1:c+1] = [resolve("handler")]
    return envelope
```

### Empty Branch Optimization

Empty branches use `pass` statement:

```python
# Source
if p["skip"]:
    pass
else:
    p = handler(p)

# Generated
if p["skip"]:
    pass
else:
    _next.append(resolve("handler"))
```

## Limitations

**Not Supported**:
- Loops (`for`, `while`) - Future enhancement
- Function calls other than actor handlers
- Multiple assignment targets: `p, q = handler(p)`
- Assignment to variables other than `p`
- Complex function arguments beyond `p`

**Workarounds**:
- Use envelope mode for custom routing logic
- Implement loop logic in actor code
- Use mutations for complex state tracking

## Integration with Asya Runtime

Compiled routers integrate seamlessly with asya-runtime:

1. **Envelope Mode**: Routers always run in envelope mode
2. **Handler Resolution**: `resolve()` function maps handler names to actor queues
3. **Route Modification**: Routers insert actors dynamically into route array
4. **Automatic Termination**: When route completes, sidecar routes to `x-sink`

## Testing

See `src/asya-cli/tests/flow/` for unit tests and `testing/component/flow-compiler/` for component tests.

**Test Coverage**:
- Parser: 95%
- Grouper: 91%
- Code Generator: 98%
- Compiler API: 93%
- DOT Generator: 100%

## Performance Considerations

- **Compile Time**: O(n) where n is number of operations
- **Router Count**: Minimized through operation batching
- **Runtime Overhead**: Minimal - routers just modify route array
- **Memory**: Constant per router execution

## Troubleshooting

**"No flow function found"**
- Check function signature: `def name(p: dict) -> dict:`
- Ensure parameter name is `p` or `payload`

**"Unsupported statement type"**
- Flow contains unsupported Python construct (loops, etc.)
- Refactor logic into actor code

**"Handler not found in environment variables"**
- Set `ASYA_HANDLER_<NAME>` for all referenced handlers
- Check handler name matches exactly (case-sensitive)

**"Multiple assignment targets"**
- Use single assignment: `p = handler(p)`
- Not: `p, q = handler(p)`

## Future Enhancements

Planned features:
- Loop support (`for`, `while`)
- Pattern matching (`match`/`case`)
- Parallel execution hints
- Flow composition (sub-flows)
- Static type checking for payload fields
