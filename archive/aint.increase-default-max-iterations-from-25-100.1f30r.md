---
title: Increase default max_iterations from 25 to 100
status: merged
priority: 2
parent: 00000
---

The current DEFAULT_MAX_LOOP_ITERATIONS is 25, which is too aggressive for
legitimate agentic workloads (e.g., ReAct loops where an LLM may need 30+
tool calls to complete a task).

Context: SQS message routes are append-only, so truly infinite iteration is
impossible (the route array would grow unboundedly and eventually hit memory
or message size limits). The guard exists as a safety net, not as a hard
operational ceiling.

Change:
- src/asya-cli/asya_cli/flow/grouper.py: DEFAULT_MAX_LOOP_ITERATIONS = 25 -> 100
- Update any tests that assert the default value of 25

This is a one-line code change + test updates.


---
**Close reason**: Default increased from 25 to 100 in PR #176


---
_Migrated from beads `asya-zffb`_
