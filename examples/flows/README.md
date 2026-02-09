# Flow DSL Examples

This directory contains example flows demonstrating the Asya Flow DSL compiler capabilities.

## Quick Start

Install `asya-cli`:
```bash
uv pip install "git+https://github.com/deliveryhero/asya#subdirectory=src/asya-cli"
uv run asya --version
```
Compile a flow:
```bash
cd examples/flows/

uv run asya flow compile ./simple_pipeline.py -o /tmp/simple_pipeline_compiled.py
```

## Overview

The Flow DSL allows you to write high-level Python functions that get compiled into distributed async actor routers for Kubernetes deployment.

## Flow DSL Constraints

Valid flow functions must follow these rules:

- Function name must start with `flow` prefix: `def flow_my_pipeline(p: dict) -> dict`
- Function signature: Exactly one parameter of type `dict`, returns `dict`
- Handler calls: `p = handler(p)` (both input and output of the handlers is `p`)
- Payload mutations: `p["key"] = value`
- Control flow: `if`/`elif`/`else`, `while` loops
- Loop control: `break`, `continue`
- Return: `return p`

## Examples

### 1. simple_pipeline.py

Basic linear flow without control structures.

**Pattern**: Sequential handler execution

```python
def flow_simple_pipeline(p: dict) -> dict:
    p = preprocess(p)
    p = analyze(p)
    p = format_output(p)
    return p
```

**Use case**: Simple data transformation pipelines

### 2. conditional_routing.py

If/elif/else branching based on payload data.

**Pattern**: Type-based routing

```python
def flow_conditional_routing(p: dict) -> dict:
    p = validate_input(p)
    if p["type"] == "A":
        p = handle_type_a(p)
    elif p["type"] == "B":
        p = handle_type_b(p)
    else:
        p = handle_default(p)
    p = finalize(p)
    return p
```

**Use case**: Dynamic routing based on message type or category

### 3. loop_processing.py

While loops with break and continue statements.

**Pattern**: Iterative processing with early exit

```python
def flow_loop_processing(p: dict) -> dict:
    p = initialize(p)
    while p["iteration"] < p["max_iterations"]:
        p = process_item(p)
        if p.get("skip_threshold_check"):
            continue
        p = check_threshold(p)
        if p["threshold_met"]:
            break
    p = finalize_loop(p)
    return p
```

**Use case**: Batch processing, retry logic, iterative refinement

**Note**: This example generates a compiler warning about potential infinite loops because the compiler cannot analyze handler function internals. The `process_item` handler actually increments `p["iteration"]`, so the loop is safe. This warning can be disabled with `--disable-infinite-loop-check`.

### 4. complex_workflow.py

Nested control structures combining multiple patterns.

**Pattern**: Complex decision trees with loops

```python
def flow_complex_workflow(p: dict) -> dict:
    p = preprocess(p)
    if not p["valid"]:
        return error_handler(p)

    if p.get("needs_enrichment"):
        while p["batch_count"] < p["max_batches"]:
            p = transform_batch(p)
            if p["quality_score"] >= 50:
                break
    p = finalize(p)
    return p
```

**Use case**: Multi-stage workflows with conditional processing paths

## Compilation

### Compile a flow

```bash
asya flow compile simple_pipeline.py
```

This generates `simple_pipeline_compiled.py` with:
- Original flow function (for local execution)
- Generated routers (for Kubernetes deployment)
- Handler resolution logic
- Initial route configuration

### Validate without compiling

```bash
asya flow validate conditional_routing.py
```

Checks syntax and DSL constraints without generating code.

## Output Structure

Compiled files contain:

1. **File header**: Auto-generation notice with timestamp
2. **resolve() function**: Maps handler names to actor names for routing
3. **INITIAL_ROUTE**: Entry point for Kubernetes execution
4. **Original flow function**: For local mode execution
5. **Generated routers**: Distributed execution handlers for each control flow point

## Execution Modes

### Local Mode

Import and call the flow function directly:

```python
from simple_pipeline_compiled import flow_simple_pipeline

result = flow_simple_pipeline({"data": "test"})
```

### Docker Mode

Run handlers in local Docker Compose (future).

### Kubernetes Mode

Deploy as AsyncActor CRDs. Send message to gateway with:

```python
{
  "id": "msg-123",
  "route": {"actors": ["if_router_1"], "current": 0},
  "payload": {"type": "A", "data": "..."}
}
```

The routers will automatically manage routing based on runtime decisions.

## Tips

### Infinite Loop Detection

The compiler detects potential infinite loops:

```python
while True:  # Warning: potential infinite loop
    p = process(p)
```

Disable with `--disable-infinite-loop-check` flag.

### Handler Resolution

Router actors resolve handler calls to actor names using environment variables:

```bash
ASYA_HANDLER_<ACTOR_NAME>="module.submodule.handler"
```

**Format**:
- **Actor name**: UPPERCASE_WITH_UNDERSCORES (converted to kebab-case for queues)
- **Handler**: Full qualified name matching `ASYA_HANDLER` format used by asya-runtime

**Examples**:

```bash
# Function handler
export ASYA_HANDLER_IMAGE_PROCESSOR="my_module.process_images"

# Class method handler
export ASYA_HANDLER_TEXT_ANALYZER="text.analyzer.TextAnalyzer.analyze"

# Deep module path
export ASYA_HANDLER_SENTIMENT_MODEL="models.nlp.sentiment.SentimentClassifier.predict"
```

**In generated routers**:

```python
# Flow code
p = process_images(p)

# Compiled router code
r['actors'][c+1:c+1] = [resolve("my_module.process_images")]

# With ASYA_HANDLER_IMAGE_PROCESSOR="my_module.process_images"
# resolve() returns "image-processor"
```

**Deployment**:

```yaml
# Docker Compose
environment:
  ASYA_HANDLER_IMAGE_PROCESSOR: "my_module.process_images"
  ASYA_HANDLER_TEXT_ANALYZER: "text.analyzer.TextAnalyzer.analyze"

# Kubernetes ConfigMap/env
- name: ASYA_HANDLER_IMAGE_PROCESSOR
  value: "my_module.process_images"
- name: ASYA_HANDLER_TEXT_ANALYZER
  value: "text.analyzer.TextAnalyzer.analyze"
```

### Best Practices

- Keep flows focused on routing logic, not business logic
- Use descriptive handler names that map to actor roles
- Minimize nesting depth for better readability
- Test locally before deploying to Kubernetes
- Use validation mode during development

## Testing

Test your flow locally:

```python
def test_simple_pipeline():
    result = flow_simple_pipeline({"input": "test"})
    assert result["preprocessed"] == True
    assert result["analyzed"] == True
    assert result["formatted"] == True
```

## Next Steps

1. Compile an example: `asya flow compile simple_pipeline.py`
2. Examine the generated code: `cat simple_pipeline_compiled.py`
3. Test locally by importing the compiled function
4. Deploy to Kubernetes using AsyncActor CRDs (see `/examples/asyas/`)

## Troubleshooting

### Common Errors

**Error**: "Flow function must accept exactly one parameter"

- Fix: Ensure function signature is `def flow_name(p: dict) -> dict`

**Error**: "Handler call must assign to 'p'"

- Fix: Always reassign handler results: `p = handler(p)`

**Error**: "Break/continue outside loop"

- Fix: Only use break/continue inside while loops

### Debugging

Use verbose mode for detailed error messages:

```bash
asya flow compile flow.py --verbose
```

Check warnings for potential issues:

```bash
asya flow validate flow.py
```
