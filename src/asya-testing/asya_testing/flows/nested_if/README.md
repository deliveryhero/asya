# Nested If Flow E2E Test

E2E test for nested if-else flow with 2 levels of branching.

## Files

- `flow.py` - Source flow DSL (hand-written)
- `routers.py` - Generated routers (auto-compiled by pre-commit hook)

## Flow Structure

```python
if level1 == "A":
    if level2 == "X":
        route_a_x()     # Path: A-X
    else:
        route_a_y()     # Path: A-Y
else:
    if level2 == "X":
        route_b_x()     # Path: B-X
    else:
        route_b_y()     # Path: B-Y
```

## Test Routes

- **Route A-X**: level1=A, level2=X → route_a_x
- **Route A-Y**: level1=A, level2=Y → route_a_y
- **Route B-X**: level1=B, level2=X → route_b_x
- **Route B-Y**: level1=B, level2=Y → route_b_y

## Actors Deployed

14 AsyncActors total (deployed via `asya-test-flows` Helm chart):

**Routers** (VFS mode):
- start-test-nested-flow
- router-test-nested-flow-line-9-if-7
- router-test-nested-flow-line-11-if-3
- router-test-nested-flow-line-12-seq-1
- router-test-nested-flow-line-15-seq-2
- router-test-nested-flow-line-19-if-6
- router-test-nested-flow-line-20-seq-4
- router-test-nested-flow-line-23-seq-5

**Handlers** (payload mode):
- validate-input
- route-a-x
- route-a-y
- route-b-x
- route-b-y
- finalize-result

## Compilation

Flow compilation is automatic via pre-commit hook:
- Edit `flow.py`
- Run `git add flow.py`
- Pre-commit hook compiles and stages `routers.py`

Manual compilation (happens with pre-commit as well):
```bash
cd testing/e2e/flows/nested_if
uv run --with-editable ../../../../src/asya-lab asya flow compile flow.py -p -o .
```

## Deployment

Actors are deployed automatically via Helm:
- Chart: `testing/e2e/charts/asya-test-flows`
- Deployed by: `testing/e2e/charts/helmfile.yaml.gotmpl`

## Running Tests

From e2e root directory:
```bash
make trigger-tests PROFILE=sqs-s3 PYTEST_OPTS="-vv -x -k flow"
```

## Test Strategy

1. **Individual route tests**: Test each of the 4 routes independently
2. **Parallel execution test**: Send all 4 routes simultaneously to verify no crosstalk

Each test:
- Sends message to start-test-nested-flow queue via SQS
- Waits for result in S3 results bucket
- Validates payload transformations through entire flow
- Verifies correct route was taken based on input conditions
