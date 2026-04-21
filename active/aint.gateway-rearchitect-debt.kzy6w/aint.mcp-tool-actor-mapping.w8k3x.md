---
title: "debt: MCP tool→actor name mapping should use MCP adapter, not heuristic"
status: open
priority: 2
tags: [gateway-rearchitect, debt, mcp]
---

## Problem

`call_mcp_tool` in `asya_testing/utils/gateway.py` dispatches directly to
`POST /api/v1/mesh/?actor=` instead of going through the MCP adapter at
`ASYA_MCP_URL/tools/call`. To resolve MCP tool names to actor names it uses:

1. A hardcoded `tool_to_actor` dict for known flows (test_pipeline → test-doubler etc.)
2. A `name.replace('_', '-')` fallback for everything else

**Why this is wrong:**
- The `_` → `-` heuristic doesn't hold in general: MCP tool name is defined by the
  flow compiler, actor name is defined by the operator. They can differ arbitrarily.
- The mapping belongs in the MCP adapter's tools registry (already has `actor:` field
  per tool in the profile yaml). The test helper duplicates and approximates it.
- Any new flow added to the test actors requires a manual update to `tool_to_actor`.

**Why we kept it:** The MCP adapter `tools/call` path had its own issues during
initial debugging and bypassing it was faster to get tests passing. It's a known
shortcut.

## Fix

`call_mcp_tool` should POST to `{ASYA_MCP_URL}/tools/call` with the standard
MCP JSON-RPC body, parse the response, and extract the task_id from the result
metadata. This is what real clients do and what the MCP adapter is designed for.

The blocking issue is that `wait_for_task_completion` uses `GET /api/v1/mesh/{id}`
(mesh-api) while MCP tools/call returns a task_id only via metadata. Need to verify
that the MCP adapter's task IDs match mesh-api task IDs (they should — both use the
same `id` from `POST /api/v1/mesh/`).

## Affected tests

All tests that use `call_mcp_tool`:
- test_gateway_routing_e2e.py
- test_sla_e2e.py
- test_multihop_e2e.py
- test_error_handling_e2e.py
- test_state_persistence_e2e.py
- test_stealth_mode_e2e.py (uses e2e_helper.call_mcp_tool)

## Related: 500 → 404 for unknown actor (already fixed)

`POST /api/v1/mesh/?actor=nonexistent` previously returned 500 when the SQS queue
didn't exist. Fixed in PR #445: `ErrActorNotFound` sentinel in queue package,
detected from `*sqstypes.QueueDoesNotExist`, mapped to 404 in `create.go`.
Also deletes the orphaned pending message from the store before returning 404.
