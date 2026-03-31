# Agent A2A Integration (External Agent <-> Asya via A2A)

## Use-Case

An organization runs multiple AI agent systems — some local (Claude Code on
developer laptops), some cloud (Google ADK agents, LangGraph services,
custom orchestrators). These agents need to collaborate on complex tasks by
delegating sub-tasks to each other via the A2A (Agent-to-Agent) protocol.

Asya acts as an A2A server: external agents discover Asya's capabilities via
the Agent Card, send tasks via `message/send`, stream progress via SSE, and
handle pause/resume for human-in-the-loop workflows.

## Why Asya

- **Full A2A implementation**: Gateway implements message/send, message/stream,
  tasks/get, tasks/cancel, and Agent Card discovery.
- **Pause/resume = A2A input_required**: When a pipeline pauses for human
  input, the A2A task state transitions to `input_required`. External agents
  can detect this and prompt their user.
- **FLY streaming = A2A artifact updates**: Real-time token streaming from
  actors maps to A2A `TaskArtifactUpdateEvent` with append semantics.
- **Durable execution**: Unlike ephemeral agent-to-agent RPC, Asya pipelines
  survive network interruptions. The external agent can disconnect and
  reconnect via `tasks/resubscribe`.

## Architecture

```
External Agent (ADK / LangGraph / Custom)
      |
      | A2A protocol (HTTPS)
      |
      v
Asya Gateway
      |
      | /.well-known/agent.json  (discovery)
      | POST /a2a/               (message/send)
      | GET /stream/{id}         (FLY events)
      |
      v
Actor Mesh (pipeline execution)
```

## Interaction Flow

1. **Discovery**: Agent fetches `GET /.well-known/agent.json`
   -> Returns capabilities, skills, auth requirements
2. **Task submission**: `POST /a2a/` with JSON-RPC `message/send`
   -> Returns `{task_id, status: "submitted"}`
3. **Streaming**: Subscribe to SSE for artifact updates and status changes
4. **Pause detection**: Status event `{state: "input_required"}`
   -> External agent prompts user for input
5. **Resume**: `POST /a2a/` with new message referencing paused task
   -> Pipeline resumes with human input
6. **Completion**: Status event `{state: "completed"}` with final artifacts

## Example: ADK Agent Delegating to Asya

```python
# In an ADK agent's tool definition
class AsyaResearchTool(Tool):
    """Delegates deep research to Asya pipeline."""

    async def run(self, query: str, depth: str = "thorough"):
        a2a_client = A2AClient("https://asya-gateway.internal")

        # Send task
        task = await a2a_client.send_message(
            message={"role": "user", "parts": [{"text": query}]},
            metadata={"depth": depth}
        )

        # Stream progress
        async for event in a2a_client.subscribe(task.id):
            if event.type == "artifact_update":
                yield StreamEvent(text=event.content)
            elif event.status == "input_required":
                # Ask user for clarification
                user_input = await self.ask_user(event.prompt)
                await a2a_client.resume(task.id, user_input)

        return task.result
```
