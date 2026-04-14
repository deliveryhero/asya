---
title: Cover all A2A with e2e tests
status: merged
priority: 2
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/a2a-protocol-compliance-gateway/0s9s.e2e-for-a2a
  - branch:a2a-protocol-compliance-gateway/0s9s.e2e-for-a2a
---

A2A auth is covered at the component level (`testing/component/gateway-a2a/`).
This task is for full Kubernetes-level A2A e2e tests.

## What needs to be added

### Auth flow in K8s context
- Deploy a JWKS server as a K8s Deployment+Service in the Kind cluster
- Configure gateway Helm values with `ASYA_A2A_JWT_JWKS_URL`, `ASYA_A2A_JWT_ISSUER`, `ASYA_A2A_JWT_AUDIENCE`
- Test authenticated A2A calls from the tester pod (reads private key from a ConfigMap/Secret generated at cluster setup time)

### A2A protocol coverage
- Agent card discovery: `GET /.well-known/agent.json` returns valid AgentCard with correct capabilities and skills
- Task send: `POST /a2a/` with `tasks/send` dispatches work through the actor mesh and returns a task ID
- Task get: `tasks/get` returns current task state
- Task subscribe (streaming): SSE stream delivers task updates as the actor pipeline progresses
- Task cancel: `tasks/cancel` transitions task to cancelled state
- Task list: `tasks/list` returns all tasks for the session
- Extended agent card: verify skills section includes tool metadata from DB

### Multi-actor pipeline via A2A
- Submit a multi-hop task via `tasks/send` and track it through to completion via `tasks/subscribe`
- Verify final status is `succeeded` with correct output

## Context
- Auth component tests: `testing/component/gateway-a2a/` (JWT + API key)
- A2A handler: `src/asya-gateway/internal/a2a/`
- Phase 2 implemented: ListTasks, CancelTask, blocking `tasks/send`, FLY streaming
- Phase 3 implemented: JWT auth, Extended Agent Card
