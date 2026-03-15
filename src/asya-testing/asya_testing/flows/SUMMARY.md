# Flow E2E Testing

E2E test infrastructure for testing compiled flow DSL in Kind cluster.

## Overview

This directory contains flow-based e2e tests that:
1. Compile flow DSL to router actors
2. Deploy routers and handlers as AsyncActors
3. Send test messages to flow entry point
4. Verify correct routing through decision tree
5. Retrieve and validate final results from S3

## Current Tests

### nested_if

Tests nested if-else flow with 2 levels of branching.

**Test routes:**
- Route A-X: level1=A, level2=X
- Route A-Y: level1=A, level2=Y
- Route B-X: level1=B, level2=X
- Route B-Y: level1=B, level2=Y

**Actors deployed:** 15 total
- 9 routers (VFS mode)
- 6 handlers (payload mode)

**Test coverage:**
- Individual route tests (4 tests)
- Parallel execution test (all routes simultaneously)

See `nested_if/README.md` for details.

## Directory Structure

```
flows/
├── __init__.py
├── SUMMARY.md                    # This file
└── nested_if/
    ├── README.md                 # Flow-specific documentation
    ├── __init__.py
    ├── flow.py                   # Source flow DSL
    ├── deploy.sh                 # Actor deployment script
    ├── compiled/
    │   ├── __init__.py
    │   └── routers.py   # Generated routers
    └── manifests/
        └── actors.yaml           # AsyncActor CRDs
```

## Running Flow Tests

### All flow tests
```bash
cd testing/e2e
make trigger-tests PROFILE=sqs-s3 PYTEST_OPTS="-vv -x -k flow"
```

### Specific flow test
```bash
make trigger-tests PROFILE=sqs-s3 PYTEST_OPTS="-vv -x -k test_route_a_x"
```

### Parallel route test only
```bash
make trigger-tests PROFILE=sqs-s3 PYTEST_OPTS="-vv -x -k test_all_routes_parallel"
```

## Deployment

Flow actors are automatically deployed during `make up` via:
1. `testing/e2e/scripts/deploy.sh` calls flow deployment scripts
2. Each flow's `deploy.sh` applies AsyncActor manifests
3. Operator creates queues and workloads
4. Tests run after all actors are ready

## Adding New Flow Tests

1. Create new directory: `flows/<flow_name>/`
2. Write flow DSL: `<flow_name>/flow.py`
3. Compile flow:
   ```bash
   cd flows/<flow_name>
   uv run --with-editable ../../src/asya-lab asya flow compile flow.py -o compiled/
   ```
4. Create manifests: `<flow_name>/manifests/actors.yaml`
   - One AsyncActor per router function (VFS mode)
   - One AsyncActor per handler function (payload mode)
5. Create deployment script: `<flow_name>/deploy.sh`
6. Write tests: `../../tests/test_flow_<flow_name>_e2e.py`
7. Update `scripts/deploy.sh` to deploy new flow
8. Document in `<flow_name>/README.md`

## Test Pattern

All flow tests follow this pattern:

```python
@pytest.mark.flow
def test_route_name(flow_helper):
    task_id = flow_helper.send_to_flow(param1=value1, param2=value2)
    result = flow_helper.wait_for_result(task_id, timeout=120)

    # Validate payload transformations
    assert result["payload"]["field"] == expected_value
    assert result["payload"]["status"] == "completed"
```

Key components:
- **flow_helper.send_to_flow()**: Creates message, sends to flow start queue
- **flow_helper.wait_for_result()**: Polls S3 for result with timeout
- **Assertions**: Verify payload fields at each stage of flow

## Architecture

Flow tests validate the complete compilation → deployment → execution pipeline:

1. **Compilation**: `asya flow compile` generates routers from DSL
2. **Deployment**: AsyncActor CRDs create queues and workloads
3. **Execution**: Messages route through decision tree
4. **Validation**: Results persisted to S3 and verified

This is the most comprehensive test type, covering:
- Flow compiler correctness
- Router logic correctness
- Operator queue/workload creation
- Sidecar message routing
- Runtime payload/message handling
- Multi-actor coordination
- End-to-end latency and reliability
