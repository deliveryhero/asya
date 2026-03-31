# Agent MCP Backend: Missing Functionality

## P0 — Blocking

### 1. No input/output schema extraction from Flow DSL

**Current state**: MCP tool schemas must be manually written in gateway
ConfigMap YAML. The flow compiler doesn't extract schemas from flow
function signatures or docstrings.

**Files**:
- `src/asya-lab/asya_lab/flow/parser.py:593-601` —
  `_validate_flow_signature()` checks param count but doesn't extract schema
- `src/asya-lab/asya_lab/flow/result_types.py` — `FlowInfo` has no schema
  fields
- Gateway ConfigMap: `input_schema` written by hand

**What's needed**:
- Compiler extracts schema from flow signature annotations:
  ```python
  @flow
  async def security_audit(p: SecurityAuditInput) -> SecurityAuditResult:
  ```
- Or from docstring/decorator:
  ```python
  @flow(input_schema={"type": "object", "properties": {"repos": ...}})
  ```
- Compiled output includes `tool.yaml` with MCP-compatible schema
- Gateway auto-discovers schemas from compiled flow artifacts

### 2. MCP tools/call returns synchronously but pipelines are async

**Current state**: `tools/call` dispatches to queue and returns `{task_id}`.
The MCP protocol expects tool results inline. Agents must separately
subscribe to the stream endpoint — a non-standard extension.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go:84-139` — returns task metadata,
  not final result
- MCP spec: `tools/call` should return `{content: [{type: "text", text: "..."}]}`

**What's needed**:
- Blocking mode for MCP tools/call: hold connection until pipeline completes,
  then return final result (like A2A blocking wait)
- Timeout parameter: `{timeout: 300}` — if pipeline finishes within timeout,
  return result; else return partial + stream URL
- This is critical for agents like Claude Code that expect synchronous tool
  results

### 3. No MCP resources support

**Current state**: Zero implementation. MCP resources would let agents
browse pipeline outputs, inspect paused tasks, or read state-proxy contents.

**Files**: No resource-related code in `src/asya-gateway/internal/mcp/`

**What's needed**:
- `resources/list` — expose paused tasks, recent results, state-proxy contents
- `resources/read` — read specific resource (task result, checkpoint, state file)
- Resource templates: `asya://tasks/{id}/result`, `asya://state/{mount}/{key}`
- Agents could then say "read the result of last security audit" without
  re-running the pipeline

---

## P1 — Important

### 4. No MCP prompts support

**Current state**: Zero implementation. MCP prompts would provide agents with
structured prompts for common operations.

**What's needed**:
- `prompts/list` — "run security audit", "analyze PR", "check compliance"
- Each prompt pre-fills tool arguments and provides context
- Useful for agents that present tool suggestions to users

### 5. No streaming tool results (MCP Streamable HTTP)

**Current state**: MCP tools return text or JSON atomically. FLY events are
only available via separate SSE endpoint, not inline in MCP response.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go` — returns full response only

**What's needed**:
- MCP Streamable HTTP transport: stream FLY events inline as MCP
  notifications during tool execution
- Progressive results: agent sees intermediate output as the pipeline runs
- Critical for long-running tools where the agent needs to show progress

### 6. Hot-reload for MCP tool registration

**Current state**: Config changes detected by filesystem watcher, but MCP
tools only registered at startup via `Registry.RegisterAll()`. Adding a new
flow requires gateway restart.

**Files**:
- `src/asya-gateway/internal/toolstore/registry.go` — `RegisterAll()` called
  once at init

**What's needed**:
- Hot-reload: new flow ConfigMap -> new MCP tool available immediately
- `tools/list` always reflects current registry state
- No gateway restart for flow additions

---

## P2 — Nice to Have

### 7. No tool usage analytics for agent teams

**What's needed**:
- Track which agents call which tools, how often, success rates
- Cost attribution per agent identity (from OAuth client_id)
- Usage dashboards for platform teams

### 8. No tool versioning

**What's needed**:
- Multiple versions of same tool: `security-audit@v1`, `security-audit@v2`
- Agents can pin to specific version or use latest
- Gradual rollout of new tool versions
