# Agent MCP Backend (External Agent -> Asya via MCP)

## Use-Case

A developer uses an agentic coding tool (Claude Code, Goose, Aider, Cursor,
Windsurf) or a custom MCP client. Most tasks are local (file edits, shell
commands, web search). But some require heavy cloud processing — "analyze all
PRs from last month", "run security audit across 20 repos", "generate API
documentation from OpenAPI specs across all microservices."

The local agent calls Asya flows as MCP tools. Asya runs the pipeline on
the company's Kubernetes cluster, streams progress via FLY events, and
returns results to the agent's context.

## Why Asya

- **MCP is the protocol**: Asya gateway already speaks MCP (tools/list,
  tools/call). Any MCP-compatible agent can use Asya flows as tools with
  zero custom integration.
- **Streaming via FLY**: Long-running pipelines stream progress tokens back
  to the agent via SSE. The developer sees real-time updates in their IDE.
- **Platform-managed infrastructure**: The agent doesn't need cloud credentials.
  It calls an MCP endpoint; the platform team handles scaling, secrets, and
  reliability.
- **Tool schemas**: Each flow is registered as an MCP tool with input schema.
  The agent knows what parameters to pass.

## Architecture

```
Developer's Machine                    Company K8s Cluster
+-------------------+                 +----------------------+
| Claude Code /     |   MCP over      | Asya Gateway         |
| Goose / Aider     |   HTTPS         |   |                  |
|                   | <-------------> |   +-> Flow A (actors) |
| Sees Asya flows   |   tools/call    |   +-> Flow B (actors) |
| as MCP tools      |   + SSE stream  |   +-> Flow C (actors) |
+-------------------+                 +----------------------+
```

## Interaction Flow

1. Agent discovers tools: `POST /mcp` -> `tools/list`
   -> Returns: `[{name: "security-audit", inputSchema: {...}}, ...]`
2. Agent calls tool: `POST /mcp` -> `tools/call`
   -> `{name: "security-audit", arguments: {repos: ["api", "web", "auth"]}}`
3. Gateway dispatches to pipeline, returns `{task_id, stream_url}`
4. Agent subscribes to `GET /stream/{task_id}` for FLY events
5. Pipeline streams progress: "Scanning api repo...", "Found 3 CVEs..."
6. Pipeline completes, agent receives final result

## Example: Security Audit Tool

```python
@flow
async def security_audit(p):
    p = await repo_scanner(p)         # fan-out per repo
    p["results"] = [
        scan_repo(repo) for repo in p["repos"]
    ]
    p = await vulnerability_aggregator(p)
    p = await severity_classifier(p)
    p = await remediation_advisor(p)
    return p
```

Registered in gateway ConfigMap:
```yaml
- name: security-audit
  actor: start_security_audit
  mcp_enabled: true
  input_schema:
    type: object
    properties:
      repos:
        type: array
        items: { type: string }
    required: [repos]
  timeout_sec: 600
```
