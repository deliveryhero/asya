---
title: "debt: test_tasks_cancel race — fast actor completes before cancel"
status: open
priority: 3
tags: [gateway-rearchitect, debt]
---

`test_tasks_cancel_transitions_to_cancelled` uses `test_slow_boundary`
(1.5s sleep) to ensure the task is still running when cancel is called.
In CI, the pubsub emulator delivers messages very quickly (<100ms) and
the actor starts processing almost immediately. The a2a-go library
completes the execution before the cancel request arrives.

The a2a library correctly rejects the cancel with `ErrTaskNotCancelable`
(code -32002) because the execution is already done — this is monotonic
ordering enforcement working as designed.

**Options:**
1. **Skip the test**: canceling a completed task is by design not allowed.
   The test assumption ("task is still running at cancel time") is flaky
   under fast environments.
2. **Use a much slower actor** (e.g., 10s sleep) in the test:
   ```python
   send_params["parts"] = [{"kind":"data","data":{"first_call":True,"extra_sleep":8}}]
   ```
   Requires modifying `slow_then_fast_handler` to accept an `extra_sleep` param.
3. **Add a hook** between submission and cancel using `task_id_ready` — the
   test already does this, but the actor may complete before `task_id_ready`
   is set because the `submitted` event arrives immediately after creation.

**Recommended fix**: Mark as expected behavior and update the assertion:
```python
# If cancel returns ErrTaskNotCancelable, task raced to completion — acceptable.
if cancel_result.get("error", {}).get("code") == -32002:
    pytest.xfail("task completed before cancel arrived (fast actor race)")
```
