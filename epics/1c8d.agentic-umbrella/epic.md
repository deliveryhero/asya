---
title: Agentic - Umbrella
status: open
priority: 2 # medium
type: epic
---

Enable Asya framework to natively support agentic use-cases, facilitating migration from orchestrator-based frameworks (Google ADK, CrewAI, DSPy, Agno, BeeAI, Strands SDK, OpenAI Agents) to choreography-based Asya.

## Vision
Extend asya flow compile capabilities to translate agentic framework code into async actor networks. Shift from centralized orchestration (RPC mindset) to decentralized choreography (Continuation-Passing Style). Agents/tools become independent actors with identities, wallets, and communication protocols - true Decentralized AI (DeAI) stack.

## Approach
- NO pip package distribution - translate user code to async actors (avoid migration burden)
- Separate tools and agents → separate actors
- Explore better actor signatures beyond current dict-based approach (e.g., tool-style: def get_weather(city: str) -> str)
- Breaking changes acceptable (no users yet)

## Key Findings from Pre-RFC (ADK Analysis)
- Dual-channel architecture: control flow (SQS/Pub/Sub) vs. streaming events (HTTP)
- asya-gateway as central communication hub, must be compliant with:
  - ACP (A2A protocol) - agent-to-agent communication
  - A2UI protocol - user agents exposed via HTTP streaming (WebSocket/SSE)
- Events NOT propagated through parent agents (unlike ADK centralized orchestration)
- Streaming events (partial text, audio, transcriptions) sent directly from actors to gateway via HTTP
- Only state transfer/control events (function calls, agent transfers, final responses) sent between actors via message queues
- Framework-level event classification - user code just yields events, runtime classifies and routes
- Session state in message payload (with compression: artifact references, compaction, sliding window)

## Open Questions
1. State management - sessions, conversation history across actor boundaries
2. Free variables - auto-append results to payload (flatten control flow like asya flow does for if/else)
3. Actor/tool detection - framework-specific semantics vs. blind decomposition at await boundary
4. Unsupported patterns - await handlers, try-catch, for/while loops, pydantic/TypedDict vs plain dict
5. Multi-framework support strategy

## Context
See /tmp/rfc-adk-to-asya.md for initial ADK exploration. Goal: interactive problem exploration, gradual issue creation for smaller tasks.

## RFC: ADK-to-Asya Compilation — Agentic Workflows on Distributed Choreography

### Executive Summary

This document proposes a compilation strategy to transform Google's Agent Development Kit (ADK) agents into Asya's distributed choreography model. ADK is a centralized, asyncio-based AI orchestration framework, while Asya is a decentralized, message-queue-based choreography system. The goal is to enable ADK agents to run as stateless Asya actors, leveraging Asya's scalability, fault tolerance, and multi-tenancy capabilities.

**Key Innovations**:
- **Dual-channel architecture**: Separating control flow (SQS messages) from data flow (streaming events), with framework-level event classification enabling simple user code
- **A2A protocol compliance**: Gateway implements the [Agent2Agent (A2A) Protocol](https://a2a-protocol.org/) for agent interoperability, enabling external agents to interact with Asya actor networks
- **Human-in-the-loop support**: Native support for interactive workflows via A2A's `input_required` task state

---

### Table of Contents

1. [Background](#background)
2. [Architecture Overview](#architecture-overview)
3. [A2A Protocol Compliance](#a2a-protocol-compliance)
4. [Event Classification & Routing](#event-classification--routing)
5. [Session State Management](#session-state-management)
6. [Service Reconstruction](#service-reconstruction)
7. [Streaming Architecture](#streaming-architecture)
8. [Human-in-the-Loop Architecture](#human-in-the-loop-architecture)
9. [Agent Compilation Strategy](#agent-compilation-strategy)
10. [Implementation Examples](#implementation-examples)
11. [Trade-offs & Design Decisions](#trade-offs--design-decisions)
12. [Open Questions](#open-questions-1)
13. [References](#references)

---

### 1. Background

#### ADK Architecture

ADK (Agent Development Kit) is Google's Python framework for building AI agents. Key characteristics:

- **Centralized orchestration**: [`Runner`](src/google/adk/runners.py:102) manages entire invocation lifecycle
- **Asyncio-based**: Concurrent execution via Python's async/await
- **Stateful sessions**: [`Session`](src/google/adk/sessions/session.py:27) accumulates conversation history
- **Event streaming**: Agents yield [`Event`](src/google/adk/events/event.py:30) objects incrementally
- **Service-oriented**: Pluggable services for artifacts, memory, sessions

**Core Components**:
- **Agent**: Blueprint defining behavior ([`BaseAgent`](src/google/adk/agents/base_agent.py:85))
- **Runner**: Execution engine ([`Runner`](src/google/adk/runners.py:102))
- **Session**: Conversation state ([`Session`](src/google/adk/sessions/session.py:27))
- **Event**: Unit of conversation ([`Event`](src/google/adk/events/event.py:30))
- **Tools**: Functions agents can call

#### Asya Architecture

Asya is a decentralized choreography framework where:

- **Actors**: Stateless microservices processing messages
- **Message queues**: SQS, Pub/Sub for actor-to-actor communication
- **Routing tables**: Stored in messages, not centralized
- **Enrichment pattern**: Monotonic computation (recommended)
- **Go sidecar**: Handles message routing, actor lifecycle

**Key Principle**: Actors are pure functions that return routing decisions, not orchestrators.

#### The Challenge

Transform ADK's centralized orchestration into Asya's distributed choreography while preserving:
- Real-time streaming (partial text, audio, video)
- Multi-agent workflows (sequential, parallel, loops)
- Session continuity across actor boundaries
- Tool execution and agent transfers

---

### 2. Architecture Overview

#### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        End User (Browser/App)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ WebSocket/SSE
                             │
                             v
                    ┌─────────────────┐
                    │  Asya Gateway   │ ← A2A + MCP compliant HTTP server
                    │  (asya.sh)      │    Stateful, handles streaming
                    └────────┬────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                v                         v
         ┌─────────────┐          ┌─────────────┐
         │ SQS Message │          │ Direct HTTP │
         │  (Control)  │          │ (Streaming) │
         └──────┬──────┘          └──────▲──────┘
                │                        │
                v                        │
         ┌─────────────┐                 │
         │  LlmAgent   │─────────────────┘
         │    Actor    │  Partial events sent directly
         │             │  to gateway via HTTP
         └──────┬──────┘
                │
                │ Returns routing decision
                v
         ┌─────────────┐
         │ Go Sidecar  │ ← Sends control messages to SQS
         └─────────────┘
```

#### Key Principles

1. **Dual-channel communication**:
   - **Control channel**: SQS/Pub/Sub for actor-to-actor orchestration
   - **Streaming channel**: HTTP/WebSocket for real-time UI updates

2. **Stateless actors**:
   - All context in message payload
   - Services initialized from environment
   - No in-memory state between messages

3. **Framework-level routing**:
   - User code just yields events
   - Framework classifies events (control vs. streaming)
   - Sidecar handles actual message sending

4. **Session as message**:
   - Full conversation history in message payload
   - Compression strategies for large sessions
   - Artifact references instead of inline data

---

### 3. A2A Protocol Compliance

#### Protocol Background

The [Agent2Agent (A2A) Protocol](https://a2a-protocol.org/latest/) is an open standard for agent-to-agent communication, developed by Google and now governed by the Linux Foundation. A2A complements MCP (Model Context Protocol):

- **MCP**: Agent-to-tool communication (how agents connect to tools, APIs, resources)
- **A2A**: Agent-to-agent communication (how agents collaborate, delegate, exchange context)

**Note**: IBM's ACP (Agent Communication Protocol) merged with A2A in September 2025. The ACP repository was archived (read-only) on August 27, 2025, and all development moved to A2A. There is no compatibility layer - ACP users migrate directly to A2A. By implementing A2A, we cover all agent interoperability needs without supporting a deprecated protocol.

#### Asya Gateway as A2A Server

The Asya Gateway will implement A2A server capabilities, allowing external agents to interact with Asya actor networks as A2A-compliant remote agents.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     External Agent (A2A Client)                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ A2A Protocol (HTTP + SSE)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Asya Gateway                                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ A2A Server Implementation                                    │    │
│  │  - Agent Card discovery                                      │    │
│  │  - Task lifecycle management                                 │    │
│  │  - Message/streaming handling                                │    │
│  │  - Push notification support                                 │    │
│  └─────────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ MCP Server Implementation (existing)                         │    │
│  │  - Tool execution                                            │    │
│  │  - Resource access                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ SQS/Internal
                               ▼
                        ┌─────────────┐
                        │ Asya Actors │
                        └─────────────┘
```

#### A2A HTTP Endpoints

The Gateway will implement these A2A-compliant endpoints:

##### Agent Discovery

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/.well-known/a2a/agent-card` | GET | Public Agent Card (capabilities, skills, auth) |
| `/agent-card:extended` | GET | Extended Agent Card (after authentication) |

##### Message Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/messages` | POST | Send message to initiate or continue task |
| `/messages:stream` | POST | Send message with streaming response (SSE) |

##### Task Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks/{task_id}` | GET | Retrieve task state and history |
| `/tasks` | GET | List tasks with filtering |
| `/tasks/{task_id}:cancel` | POST | Cancel a running task |
| `/tasks/{task_id}:subscribe` | GET | Subscribe to task updates (SSE stream) |

##### Push Notifications (Optional)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks/{task_id}/pushNotificationConfigs` | POST | Create push notification config |
| `/tasks/{task_id}/pushNotificationConfigs/{id}` | GET | Get config |
| `/tasks/{task_id}/pushNotificationConfigs` | GET | List configs |
| `/tasks/{task_id}/pushNotificationConfigs/{id}` | DELETE | Delete config |

#### A2A Task States

A2A defines a task lifecycle that maps to Asya's envelope states:

| A2A State | Description | Asya Mapping |
|-----------|-------------|--------------|
| `submitted` | Task created, not yet processing | Envelope queued |
| `working` | Task actively processing | Actor processing |
| `input_required` | Waiting for client/human input | Suspended (→ happy-end → S3) |
| `completed` | Task finished successfully | happy-end received |
| `failed` | Task encountered error | error-end received |
| `cancelled` | Task terminated by client | Envelope cancelled |
| `rejected` | Agent declined the task | Validation failed |
| `auth_required` | Additional auth needed | Auth challenge |

#### Agent Card Format

The Gateway publishes an Agent Card at `/.well-known/a2a/agent-card`:

```json
{
  "name": "Asya Agent Network",
  "description": "Distributed AI agent orchestration via Asya actor mesh",
  "version": "1.0.0",
  "protocol_versions": ["1.0"],
  "supported_interfaces": [
    {
      "type": "rest",
      "url": "https://gateway.asya.example.com"
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "extendedAgentCard": true
  },
  "security_schemes": {
    "bearer": {
      "type": "http",
      "scheme": "bearer"
    },
    "oauth2": {
      "type": "oauth2",
      "flows": {
        "clientCredentials": {
          "tokenUrl": "https://auth.example.com/token",
          "scopes": {
            "agent:invoke": "Invoke agent tasks",
            "agent:read": "Read task status"
          }
        }
      }
    }
  },
  "default_input_modes": ["application/json", "text/plain"],
  "default_output_modes": ["application/json", "text/plain", "text/event-stream"],
  "skills": [
    {
      "id": "code-assistant",
      "name": "Code Assistant",
      "description": "AI-powered coding assistance with file operations",
      "tags": ["coding", "development"]
    },
    {
      "id": "data-pipeline",
      "name": "Data Pipeline Executor",
      "description": "Execute multi-stage data processing workflows",
      "tags": ["data", "etl"]
    }
  ]
}
```

#### A2A Message Format

Messages follow A2A's multimodal part structure:

```json
{
  "message_id": "msg-123",
  "context_id": "conversation-456",
  "task_id": "task-789",
  "role": "user",
  "parts": [
    {
      "text": "Analyze this code and suggest improvements",
      "media_type": "text/plain"
    },
    {
      "url": "s3://bucket/code-snippet.py",
      "media_type": "text/x-python"
    }
  ]
}
```

#### Mapping A2A to Asya Envelopes

When the Gateway receives an A2A message, it translates to an Asya envelope:

```python
# A2A Message → Asya Envelope translation
def a2a_to_envelope(message: A2AMessage, skill_id: str) -> AsyaEnvelope:
    return {
        "id": generate_envelope_id(),
        "route": {
            "actors": resolve_skill_to_actors(skill_id),
            "current": 0
        },
        "headers": {
            "a2a_task_id": message.task_id,
            "a2a_context_id": message.context_id,
            "a2a_message_id": message.message_id
        },
        "payload": {
            "parts": message.parts,
            "session": load_or_create_session(message.context_id)
        }
    }
```

#### Streaming via SSE

A2A streaming maps directly to Asya's dual-channel architecture:

```
Client                    Gateway                     Actor
  │                          │                          │
  │ POST /messages:stream    │                          │
  │ ───────────────────────► │                          │
  │                          │ SQS envelope             │
  │                          │ ─────────────────────────►
  │                          │                          │
  │ ◄─── SSE: TaskStatusUpdateEvent (working)          │
  │                          │                          │
  │                          │ ◄── streaming event ────│
  │ ◄─── SSE: partial text   │                          │
  │                          │                          │
  │                          │ ◄── streaming event ────│
  │ ◄─── SSE: partial text   │                          │
  │                          │                          │
  │                          │ ◄── control event ──────│
  │ ◄─── SSE: TaskStatusUpdateEvent (completed)        │
  │                          │                          │
  │ ◄─── SSE: TaskArtifactUpdateEvent                  │
  │                          │                          │
```

#### Protocol Stack: MCP, A2A, AG-UI, A2UI

The Gateway implements multiple complementary protocols on the same server:

| Protocol | Purpose | Type | Base Path |
|----------|---------|------|-----------|
| **A2A** | Agent-to-agent communication | REST + SSE | `/` (root) |
| **MCP** | Agent-to-tool communication | JSON-RPC 2.0 | `/mcp` |
| **AG-UI** | Agent-to-user streaming | Event-based SSE | `/ag-ui` |
| **A2UI** | Declarative UI payloads | JSON format | (via A2A/AG-UI) |

**Protocol relationships**:
```
┌─────────────────────────────────────────────────────────────────┐
│                    Asya Gateway Protocol Stack                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│   │    MCP      │     │    A2A      │     │   AG-UI     │       │
│   │ Agent↔Tool  │     │ Agent↔Agent │     │ Agent↔User  │       │
│   │   /mcp      │     │  / (root)   │     │  /ag-ui     │       │
│   └─────────────┘     └─────────────┘     └─────────────┘       │
│                              │                   │               │
│                              └───────┬───────────┘               │
│                                      ▼                           │
│                              ┌───────────────┐                   │
│                              │     A2UI      │                   │
│                              │ (UI payloads) │                   │
│                              └───────────────┘                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Routing convention**:
- A2A endpoints at root level (`/messages`, `/tasks/{id}`, etc.)
- MCP endpoint at `/mcp` (single JSON-RPC endpoint)
- AG-UI endpoint at `/ag-ui` (SSE event stream)
- Discovery at `/.well-known/a2a/agent-card` (standard well-known URI)

**Why this layout?**
- A2A is the primary external interface (root path)
- MCP is a secondary interface for tool-oriented clients
- AG-UI enables rich frontend integration (CopilotKit, etc.)
- No collision: Each uses different paths and protocols

**Migration note**: Current Gateway uses `/envelopes/*` routes. These will be migrated to A2A-compliant `/messages` and `/tasks/*` endpoints. See epic `asya-7j1` for implementation plan.

**Architectural relationship**: External agents use A2A to delegate tasks to Asya. Frontends use AG-UI for real-time streaming. Internally, Asya actors may use MCP to access tools. The Gateway serves all roles.

#### AG-UI Event Types

AG-UI defines 17 event types for agent-to-frontend communication:

| Category | Events | Purpose |
|----------|--------|---------|
| **Lifecycle** | `RunStarted`, `RunFinished`, `RunError`, `StepStarted`, `StepFinished` | Execution state |
| **Text** | `TextMessageStart`, `TextMessageContent`, `TextMessageEnd` | Streaming text |
| **Tools** | `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult` | Tool invocations |
| **State** | `StateSnapshot`, `StateDelta`, `MessagesSnapshot` | UI state sync |
| **Special** | `RawEvent`, `CustomEvent` | Extensions |

**AG-UI endpoint**:
```
GET /ag-ui/stream?thread_id=xxx&run_id=yyy
Content-Type: text/event-stream

event: RUN_STARTED
data: {"thread_id": "xxx", "run_id": "yyy"}

event: TEXT_MESSAGE_START
data: {"message_id": "msg-1", "role": "assistant"}

event: TEXT_MESSAGE_CONTENT
data: {"message_id": "msg-1", "delta": "Hello"}

event: TEXT_MESSAGE_END
data: {"message_id": "msg-1"}

event: RUN_FINISHED
data: {"thread_id": "xxx", "run_id": "yyy"}
```

#### A2UI Integration (Optional)

A2UI is a declarative UI format that can be transported via A2A or AG-UI. If actors generate A2UI payloads, they're delivered as:
- A2A: `TaskArtifactUpdateEvent` with `media_type: "application/a2ui+json"`
- AG-UI: `CustomEvent` with `name: "A2UI_COMPONENT"`

A2UI support is optional and depends on whether actors generate dynamic UIs.

#### Authentication Alignment

A2A supports OpenAPI-compatible auth schemes. Gateway will implement:

1. **Bearer Token** (primary): JWT validation against configured OIDC provider
2. **OAuth2 Client Credentials** (machine-to-machine): For external agent integration
3. **API Key** (simple): For development/testing

Auth configuration flows from Gateway's existing auth middleware, extended with A2A's security scheme advertisement. Both A2A and MCP endpoints share the same auth layer.

---

### 4. Event Classification & Routing

#### ADK Event Types

ADK agents yield two categories of events:

##### Streaming Events (Display-Only)

**Partial Text** ([`llm_response.py:71`](src/google/adk/models/llm_response.py:71)):
```python
Event(
    partial=True,  # Incomplete text chunk
    content=Content(parts=[Part(text="Hello wor")])
)
```
- **Purpose**: Show typing animation in UI
- **Not actionable**: Cannot make decisions on partial text
- **Not persisted**: Skipped by session service ([`runners.py:829`](src/google/adk/runners.py:829))

**Audio/Video Chunks** ([`base_llm_flow.py:389`](src/google/adk/flows/llm_flows/base_llm_flow.py:389)):
```python
Event(
    content=Content(parts=[Part(inline_data=Blob(
        data=b"<audio bytes>",
        mime_type="audio/pcm"
    ))])
)
```
- **Purpose**: Real-time audio playback
- **High frequency**: 10-100 events/second
- **Large payload**: Can be MBs per event

**Transcriptions** ([`llm_response.py:113`](src/google/adk/models/llm_response.py:113)):
```python
Event(
    input_transcription=Transcription(text="Hello", partial=True)
)
```
- **Purpose**: Show what user/model said
- **Metadata only**: Not used for decision-making

##### Control Events (Actionable)

**Function Calls**:
```python
Event(
    partial=False,
    content=Content(parts=[Part(function_call=FunctionCall(
        name="search",
        args={"query": "weather"}
    ))])
)
```
- **Triggers**: Tool execution
- **Routing**: Send to tool executor actor

**Function Responses**:
```python
Event(
    content=Content(parts=[Part(function_response=FunctionResponse(
        name="search",
        response={"result": "Sunny, 72°F"}
    ))])
)
```
- **Triggers**: Resume agent with tool result
- **Routing**: Send back to agent actor

**Agent Transfers** ([`event_actions.py:73`](src/google/adk/events/event_actions.py:73)):
```python
Event(
    actions=EventActions(transfer_to_agent="specialist_agent")
)
```
- **Triggers**: Delegate to another agent
- **Routing**: Send to target agent actor

**Final Responses**:
```python
Event(
    partial=False,
    content=Content(parts=[Part(text="Here's the weather: Sunny, 72°F")])
)
```
- **Triggers**: End of invocation
- **Routing**: Send to gateway for user

#### Framework-Level Classification

**User Code** (Simple):
```python
# actor_handler.py
async def handle_llm_agent(message: dict):
    """User just yields events - framework handles routing."""
    context = create_context(message)

    async for event in MY_AGENT.run_async(context):
        yield event  # Framework classifies and routes

    yield {"type": "end"}  # Signal completion
```

**Framework Runtime** (`asya_runtime.py` - mounted as ConfigMap):
```python
async def classify_event(event: dict) -> str:
    """Classify event type for routing."""
    # Partial/streaming events → SSE
    if event.get("partial") is True:
        return "sse"

    # Transcription events → SSE
    if event.get("input_transcription") or event.get("output_transcription"):
        return "sse"

    # Audio/video chunks → WebSocket
    content_parts = event.get("content", {}).get("parts", [])
    if content_parts:
        inline_data = content_parts[0].get("inline_data", {})
        mime_type = inline_data.get("mime_type", "")
        if mime_type.startswith(("audio/", "video/")):
            return "ws"

    # Control events → Message queue
    if content_parts:
        if content_parts[0].get("function_call"):
            return "control"
        if content_parts[0].get("function_response"):
            return "control"

    if event.get("actions", {}).get("transfer_to_agent"):
        return "control"

    if event.get("type") == "end":
        return "control"

    if event.get("partial") is False and event.get("content"):
        return "control"

    return "control"  # Default

async def wrap_user_handler(user_handler, message: dict):
    """Framework wrapper - classifies and routes events."""
    session = message["session"]

    async for event in user_handler(message):
        event_type = await classify_event(event)

        if event_type == "control":
            # Control event - include full session for next actor
            await send_to_sidecar("control", {
                "route": determine_route(event),
                "payload": {
                    "session": session,
                    "event": event
                }
            })
        else:
            # Streaming event - minimal payload
            await send_to_sidecar(event_type, {
                "invocation_id": message["invocation_id"],
                "session_id": session["id"],
                "event": event
            })

def determine_route(event: dict) -> list[str]:
    """Determine next actor based on event content."""
    if event.get("type") == "end":
        return ["gateway"]

    content_parts = event.get("content", {}).get("parts", [])
    if content_parts and content_parts[0].get("function_call"):
        return ["tool_executor"]

    if event.get("actions", {}).get("transfer_to_agent"):
        return [event["actions"]["transfer_to_agent"]]

    return ["gateway"]  # Final response
```

**Go Sidecar** (Routes messages):
```go
func handleEventFromRuntime(eventMsg EventMessage) {
    switch eventMsg.EventType {
    case "control":
        // Send to SQS/Pub/Sub for next actor
        sendToMessageQueue(eventMsg.Payload)

    case "sse":
        // Forward to HTTP gateway for SSE streaming
        forwardToGateway("/stream/sse", eventMsg.Payload)

    case "ws":
        // Forward to HTTP gateway for WebSocket streaming
        forwardToGateway("/stream/ws", eventMsg.Payload)
    }
}
```

---

### 5. Session State Management

#### Session Structure

From [`session.py:27-50`](src/google/adk/sessions/session.py:27):

```python
class Session(BaseModel):
    id: str                    # Session identifier
    app_name: str              # Application name
    user_id: str               # User identifier
    state: dict[str, Any]      # Key-value state (agent outputs, temp vars)
    events: list[Event]        # Full conversation history
    last_update_time: float    # Timestamp
```

**What's in `events`?**
- User messages
- Agent responses (text, function calls, transfers)
- Tool execution results
- State changes ([`event_actions.py:66`](src/google/adk/events/event_actions.py:66))
- Artifact references ([`event_actions.py:69`](src/google/adk/events/event_actions.py:69))

#### Size Analysis

**Typical conversation (10 turns)**:
- ~10-20 events (user + agent + tools)
- **Text-only**: 5-50 KB JSON
- **With images/audio inline**: Can be **MBs** (base64-encoded)
- **After 100 turns**: 50-500 KB (text) or **10s of MBs** (multimodal)

**Message queue limits**:
- AWS SQS: 256 KB per message
- Google Pub/Sub: 10 MB per message

#### Compression Strategies

##### Strategy 1: Artifact References (Primary)

**Problem**: Images/audio in `inline_data` bloat messages

**Solution**: Store large blobs in artifact service, keep only references

```python
# Before (bloated):
event.content.parts[0].inline_data = Blob(
    data=b"<10MB image>",
    mime_type="image/png"
)

# After (compact):
event.content.parts[0].file_data = FileData(
    file_uri="gs://artifacts/session123/image_0.png"
)
event.actions.artifact_delta = {"image_0.png": 1}  # version 1
```

**Impact**: Reduces event size from MBs to ~100 bytes per artifact

**Implementation**: ADK already supports this via [`artifact_util.py`](src/google/adk/artifacts/artifact_util.py)

##### Strategy 2: Event Compaction

ADK's built-in compaction ([`compaction.py`](src/google/adk/apps/compaction.py)):

```python
# Original: 50 events (20 KB)
events[0:40]  # Old conversation

# Compacted: 1 event (2 KB)
CompactedEvent(
    compaction=EventCompaction(
        compacted_content="User asked about weather, agent provided forecast...",
        start_timestamp=1234567890.0,
        end_timestamp=1234567950.0
    )
)
```

**For Asya**: Run compaction as a **separate actor** when message size exceeds threshold:

```
LlmAgent → (message > 200KB) → CompactionActor → (compacted message) → NextAgent
```

**Trigger**: Framework detects message size before sending to sidecar

##### Strategy 3: Sliding Window

Keep only recent events in message, rest in shared store:

```python
# Message payload
{
    "session_id": "user123_session456",
    "recent_events": events[-10:],  # Last 10 events
    "total_event_count": 150,
    "event_store_pointer": "gs://sessions/user123_session456/events.jsonl"
}
```

**When to fetch full history**: Only when agent needs it (e.g., memory retrieval)

**Trade-off**: Adds latency for full history fetch, but keeps messages small

##### Strategy 4: Binary Serialization

| Format | Size (10 events) | Pros | Cons |
|--------|------------------|------|------|
| JSON | 20 KB | Human-readable, debuggable | Verbose |
| MessagePack | 12 KB | Faster, smaller | Binary |
| Protobuf | 8 KB | Smallest, schema validation | Requires .proto files |

**Recommendation**: Start with JSON + artifact references. Add MessagePack if hitting size limits.

#### Recommended Approach

1. **Always**: Use artifact references for images/audio/video
2. **If session > 50 events**: Route to compaction actor
3. **If message > 200 KB**: Use sliding window
4. **If still too large**: Switch to MessagePack

---

### 6. Service Reconstruction

#### The Challenge

ADK's [`InvocationContext`](src/google/adk/agents/invocation_context.py:98) contains non-serializable services:

```python
class InvocationContext:
    artifact_service: BaseArtifactService      # GCS client, file handles
    session_service: BaseSessionService        # Spanner connection, DB pool
    memory_service: BaseMemoryService          # Vector DB client
    credential_service: BaseCredentialService  # OAuth tokens, API keys
    # ... other fields
```

These **cannot** be serialized into messages.

#### Solution: Environment-Based Configuration

**Deployment-Time Configuration** (Kubernetes):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-agent-actor
spec:
  template:
    spec:
      containers:
      - name: actor
        image: my-llm-agent:latest
        env:
          # ADK service configurations
          - name: ADK_ARTIFACT_SERVICE_TYPE
            value: "gcs"
          - name: ADK_ARTIFACT_SERVICE_BUCKET
            value: "my-artifacts"

          - name: ADK_SESSION_SERVICE_TYPE
            value: "spanner"
          - name: ADK_SESSION_SERVICE_INSTANCE
            value: "my-instance"
          - name: ADK_SESSION_SERVICE_DATABASE
            value: "sessions"

          - name: ADK_MEMORY_SERVICE_TYPE
            value: "vertex_ai_rag"
          - name: ADK_MEMORY_SERVICE_CORPUS
            value: "my-corpus"

          # Asya gateway URL
          - name: ASYA_GATEWAY_URL
            value: "http://gateway.asya.svc.cluster.local:8080"
```

**Service Factory** (Fail-Fast Initialization):

```python
# services.py - Initialized at module load time
import os
from typing import Optional

# Global service instances (one per pod)
_artifact_service: Optional[BaseArtifactService] = None
_session_service: Optional[BaseSessionService] = None
_memory_service: Optional[BaseMemoryService] = None

def init_services():
    """Initialize all services at startup. Fail-fast if misconfigured."""
    global _artifact_service, _session_service, _memory_service

    # Artifact Service
    artifact_type = os.environ.get("ADK_ARTIFACT_SERVICE_TYPE")
    if artifact_type == "gcs":
        from google.adk.artifacts.gcs_artifact_service import GCSArtifactService
        _artifact_service = GCSArtifactService(
            bucket=os.environ["ADK_ARTIFACT_SERVICE_BUCKET"]
        )
    elif artifact_type == "file":
        from google.adk.artifacts.file_artifact_service import FileArtifactService
        _artifact_service = FileArtifactService(
            base_path=os.environ.get("ADK_ARTIFACT_SERVICE_PATH", "/tmp/artifacts")
        )
    else:
        raise ValueError(f"Unknown artifact service type: {artifact_type}")

    # Session Service
    session_type = os.environ.get("ADK_SESSION_SERVICE_TYPE")
    if session_type == "spanner":
        from google.adk.sessions.database_session_service import DatabaseSessionService
        _session_service = DatabaseSessionService(
            instance=os.environ["ADK_SESSION_SERVICE_INSTANCE"],
            database=os.environ["ADK_SESSION_SERVICE_DATABASE"]
        )
    elif session_type == "in_memory":
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        _session_service = InMemorySessionService()
    else:
        raise ValueError(f"Unknown session service type: {session_type}")

    # Memory Service (optional)
    memory_type = os.environ.get("ADK_MEMORY_SERVICE_TYPE")
    if memory_type == "vertex_ai_rag":
        from google.adk.memory.vertex_ai_rag_memory_service import VertexAiRagMemoryService
        _memory_service = VertexAiRagMemoryService(
            corpus_id=os.environ["ADK_MEMORY_SERVICE_CORPUS"]
        )

def get_artifact_service() -> BaseArtifactService:
    if _artifact_service is None:
        raise RuntimeError("Services not initialized")
    return _artifact_service

def get_session_service() -> BaseSessionService:
    if _session_service is None:
        raise RuntimeError("Services not initialized")
    return _session_service

def get_memory_service() -> Optional[BaseMemoryService]:
    return _memory_service

# Initialize at module load time (fail-fast)
init_services()
```

**Actor Usage**:

```python
# actor_handler.py
from services import get_artifact_service, get_session_service

# Services already initialized
ARTIFACT_SERVICE = get_artifact_service()
SESSION_SERVICE = get_session_service()

async def handle_llm_agent(message: dict):
    context = InvocationContext(
        artifact_service=ARTIFACT_SERVICE,  # Global instance
        session_service=SESSION_SERVICE,
        session=Session.model_validate(message["session"]),
        agent=MY_AGENT,
        invocation_id=message["invocation_id"]
    )

    async for event in MY_AGENT.run_async(context):
        yield event
```

#### Advantages

✅ **Fail-fast**: Misconfiguration detected at startup, not runtime
✅ **Simple**: No service locator pattern, no lazy initialization
✅ **Message size**: No service configs in messages
✅ **Performance**: Services initialized once, reused for all messages
✅ **Pure Python**: No external dependencies, just environment variables

#### Multi-Tenancy

If different users need different artifact buckets:

```python
# Message contains tenant-specific identifiers
{
    "session": {...},
    "tenant_id": "customer_123"
}

# Service uses tenant_id to route to correct bucket
async def handle_llm_agent(message: dict):
    tenant_id = message["tenant_id"]

    # Artifact service uses tenant_id in path
    await ARTIFACT_SERVICE.save_artifact(
        app_name=f"{tenant_id}_myapp",  # Tenant-specific
        user_id=message["session"]["user_id"],
        session_id=message["session"]["id"],
        filename="image.png",
        artifact=...
    )
```

---

### 7. Streaming Architecture

#### Gateway Responsibilities

The Asya gateway (asya.sh) is a **stateful** MCP-compliant HTTP server that:

1. **Accepts client connections**: WebSocket/SSE from browsers/apps
2. **Converts HTTP → SQS**: User messages become actor messages
3. **Receives streaming events**: HTTP POST from actor sidecars
4. **Forwards to clients**: Maintains `invocation_id → WebSocket` mapping
5. **Handles MCP protocol**: Exposes tools, resources, prompts

#### Session Management in Gateway

**Mapping invocation_id → WebSocket connection**:

```python
class Gateway:
    def __init__(self):
        # invocation_id → WebSocket connection
        self.active_connections: dict[str, WebSocket] = {}

    async def handle_new_request(self, websocket: WebSocket, user_message: str):
        """User sends message via WebSocket."""
        invocation_id = generate_invocation_id()

        # Track this connection
        self.active_connections[invocation_id] = websocket

        # Send to actor via SQS
        await send_to_sqs({
            "route": ["llm_agent"],
            "payload": {
                "invocation_id": invocation_id,
                "session": await load_session(websocket.session_id),
                "user_message": user_message
            }
        })

    async def handle_streaming_event(self, event: dict):
        """Actor sends streaming event via HTTP POST."""
        invocation_id = event["invocation_id"]

        # Find the WebSocket connection for this invocation
        if websocket := self.active_connections.get(invocation_id):
            # Forward to client
            await websocket.send_json(event)

    async def handle_final_event(self, event: dict):
        """Actor sends final event - close connection."""
        invocation_id = event["invocation_id"]

        if websocket := self.active_connections.get(invocation_id):
            await websocket.send_json(event)
            await websocket.close()
            del self.active_connections[invocation_id]
```

#### Scalability Considerations

##### Horizontal Scaling with Sticky Sessions

```
                    ┌─────────────┐
                    │ Load Balancer│
                    │  (Sticky)    │
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          v                v                v
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ Gateway 1│     │ Gateway 2│     │ Gateway 3│
    └────┬─────┘     └────┬─────┘     └────┬─────┘
         │                │                │
         └────────────────┼────────────────┘
                          │
                    ┌─────▼──────┐
                    │   Redis    │ ← Shared invocation_id → gateway mapping
                    └────────────┘
```

**How it works**:
1. Client connects → Load balancer assigns to Gateway 1 (sticky session)
2. Gateway 1 stores `invocation_id → "gateway-1"` in Redis
3. Actor sends streaming event → HTTP POST to any gateway
4. Gateway checks Redis → "This invocation is on gateway-1"
5. Gateway forwards → HTTP POST to gateway-1 (internal)
6. Gateway-1 sends → WebSocket to client

##### Stateless Gateway Alternative (SSE)

```python
@app.get("/stream/{invocation_id}")
async def stream_events(invocation_id: str):
    """Client opens SSE connection - gateway is stateless."""
    async def event_generator():
        # Subscribe to Redis pub/sub for this invocation
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"invocation:{invocation_id}")

        async for message in pubsub.listen():
            yield f"data: {message['data']}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Actor publishes streaming event
async def send_streaming_event(event: dict):
    await redis.publish(
        f"invocation:{event['invocation_id']}",
        json.dumps(event)
    )
```

**Trade-off**: Adds Redis dependency but enables true stateless gateways.

#### Complete Message Flow

```
1. User: "Generate an image of a dog"
   ↓ WebSocket
2. Gateway → SQS message → LlmAgent actor
   ↓
3. LlmAgent actor yields:

   Event 1 (partial=True): "I'll"
     → Framework: classify as "sse"
     → Sidecar: HTTP POST to gateway /stream/sse
     → Gateway: Send to user via WebSocket ✓

   Event 2 (partial=True): "I'll generate"
     → Framework: classify as "sse"
     → Sidecar: HTTP POST to gateway
     → Gateway: Send to user via WebSocket ✓

   Event 3 (partial=False): function_call(generate_image, "dog")
     → Framework: classify as "control"
     → Sidecar: Send to SQS with route=["tool_executor"]
     → (NOT sent to gateway yet)
   ↓
4. ToolExecutor actor:
   - Executes tool
   - Yields function_response
     → Framework: classify as "control"
     → Sidecar: Send to SQS with route=["llm_agent"]
   ↓
5. LlmAgent actor yields:

   Event 4 (partial=True): "Here's"
     → Gateway → User ✓

   Event 5 (partial=True): "Here's your"
     → Gateway → User ✓

   Event 6 (partial=False): final_response with image reference
     → Framework: classify as "control"
     → Sidecar: Send to SQS with route=["gateway"]

   Event 7 (type="end"):
     → Framework: classify as "control"
     → Sidecar: Send to SQS with route=["gateway"]
   ↓
6. Gateway receives final event → Sends to user → Closes WebSocket
```

**Key insight**: User sees **all** events (streaming + control), but actors only process **control** events.

---

### 8. Human-in-the-Loop Architecture

#### The Challenge

Interactive agents (coding assistants, approval workflows) require **bidirectional** communication:

- **Approval gates**: "I'm about to delete 15 files. Proceed?"
- **Clarification requests**: "Which authentication method?"
- **Mid-stream corrections**: User interrupts with new instructions

This differs from the unidirectional "agent generates, user watches" model. The agent must **suspend** while waiting for human input, potentially for minutes or hours.

#### A2A Alignment

The A2A protocol natively supports this pattern through the `input_required` task state. When an agent needs human input:

1. Task transitions to `input_required` state
2. Client receives `TaskStatusUpdateEvent` with the question/options
3. Client sends response via `POST /messages` with same `task_id`
4. Task resumes processing (state → `working`)

This is a core A2A capability, not a custom extension. The `input_required` state is specifically designed for human-in-the-loop workflows.

#### Design Principles

1. **Actors remain stateless**: All state lives in the envelope (message)
2. **Gateway stays thin**: Postgres stores only A2A task metadata, not conversation history
3. **S3 for persistence**: Conversation state persisted via existing `happy-end` crew actor
4. **Resume capability**: Suspended conversations can be resumed from S3
5. **A2A compliance**: Use standard `input_required` state and A2A message flow

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           User (CLI/UI)                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP (request + SSE streaming)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Gateway                                      │
│  - Postgres: envelope_id → S3 path (thin registry)                  │
│  - NOT storing: conversation history, session state                 │
│  - Linear growth: O(active_conversations), not O(total_messages)    │
└──────────┬─────────────────────────────────────────────┬────────────┘
           │ SQS (envelope with full state)              │ SSE
           ▼                                             │
┌────────────────────┐                                   │
│   Agent Actor      │───────────────────────────────────┘
│ - Stateless        │   streaming events
│ - Full state in    │
│   envelope payload │
└──────────┬─────────┘
           │
           ▼ (routes to happy-end when done or waiting)
┌────────────────────┐
│  happy-end → S3    │  Persists envelope (full conversation state)
└────────────────────┘
```

#### Suspension Flow (Agent Needs Human Input)

```
1. Agent processing turn...
   │
   ▼
2. Agent needs human input (approval, clarification)
   │
   ▼
3. Agent yields A2A-compliant message (role=agent):
   {
     "role": "agent",
     "parts": [
       {"text": "Delete these 15 files?", "media_type": "text/plain"},
       {"data": {"type": "input_request", "options": ["yes", "no", "show files"]}, "media_type": "application/json"}
     ]
   }
   │
   ▼
4. Framework routes envelope to happy-end
   - Envelope contains FULL conversation state
   - happy-end persists to S3
   │
   ▼
5. Gateway receives notification:
   - Updates A2A task state → `input_required`
   - Stores: task_id → S3 path (Postgres)
   - Streams to client: `TaskStatusUpdateEvent` with question + options
   │
   ▼
6. User sees question, connection can close
   (User may take minutes/hours to respond)
```

#### Resume Flow (Human Responds)

```
1. Client sends response via A2A message:
   POST /messages
   {
     "message_id": "msg-456",
     "task_id": "task-123",
     "context_id": "ctx-789",
     "role": "user",
     "parts": [{"text": "yes", "media_type": "text/plain"}]
   }
   │
   ▼
2. Gateway looks up S3 path from Postgres using task_id
   │
   ▼
3. Gateway fetches envelope from S3
   │
   ▼
4. Gateway creates new Asya envelope (task state → `working`):
   {
     "id": "new-envelope-id",
     "parent_id": "{original-envelope-id}",
     "route": {"actors": ["agent"], "current": 0},
     "headers": {
       "a2a_task_id": "task-123",
       "a2a_context_id": "ctx-789",
       "a2a_message_id": "msg-456"
     },
     "payload": {
       "session": <restored from S3>,
       "human_response": {"parts": [{"text": "yes", "media_type": "text/plain"}]}
     }
   }
   │
   ▼
5. Agent actor receives message, continues execution
```

#### Task and Context Identity (A2A Alignment)

A2A defines two identity concepts that map to Asya:

| A2A Concept | Description | Asya Mapping |
|-------------|-------------|--------------|
| `task_id` | Single request-response cycle | Envelope ID |
| `context_id` | Multi-turn conversation grouping | Session ID / Conversation ID |

Gateway's Postgres table uses A2A terminology:

```sql
CREATE TABLE a2a_tasks (
    task_id        TEXT PRIMARY KEY,
    context_id     TEXT NOT NULL,     -- Groups related tasks into conversations
    s3_path        TEXT NOT NULL,     -- Location of persisted envelope
    status         TEXT NOT NULL,     -- A2A states: 'working', 'input_required', 'completed', 'failed'
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);

CREATE INDEX idx_tasks_context ON a2a_tasks(context_id);
CREATE INDEX idx_tasks_status ON a2a_tasks(status);
```

**A2A compliance note**: The `context_id` allows grouping multiple tasks into a logical conversation, enabling queries like "show all tasks in this conversation" via `GET /tasks?context_id=ctx-789`.

#### Advantages

| Aspect | Benefit |
|--------|---------|
| **Gateway simplicity** | Postgres grows with active tasks, not message count |
| **Actor statelessness** | No in-memory state; envelope IS the state |
| **Fault tolerance** | Crash-safe; state persisted to S3 before suspension |
| **Scalability** | Gateway instances share Postgres; actors are ephemeral |
| **Resume latency** | Cold start acceptable (seconds) for human-timescale waits |
| **A2A interoperability** | External A2A clients can interact with Asya agents natively |

#### Future Enhancement: Checkpointing

For long-running agent turns (not just human waits), periodic checkpointing to S3 could enable:
- Resume after actor crash mid-execution
- Horizontal scaling of single conversation across actors

This is out of scope for initial implementation but the architecture supports it.

---

### 9. Agent Compilation Strategy

#### Supported Agent Types

ADK provides several built-in agent types. We compile these **declaratively** (recognize patterns, not disassemble implementation):

##### LlmAgent

**ADK Definition** ([`llm_agent.py:183`](src/google/adk/agents/llm_agent.py:183)):
```python
root_agent = Agent(
    name="my_agent",
    model="gemini-2.5-flash",
    instruction="You are a helpful assistant",
    tools=[search_tool, calculator_tool]
)
```

**Asya Compilation**: Single actor

```
┌─────────────┐
│  LlmAgent   │
│    Actor    │
└─────────────┘
```

**Actor behavior**:
- Runs ADK's reason-act loop internally
- Yields events (streaming + control)
- Framework routes to tool executor or next agent

##### SequentialAgent

**ADK Definition** ([`sequential_agent.py:47`](src/google/adk/agents/sequential_agent.py:47)):
```python
workflow = SequentialAgent(
    name="workflow",
    sub_agents=[agent_a, agent_b, agent_c]
)
```

**Asya Compilation**: Linear chain of actors, as a pre-defined pre-compiled flow.

```
┌─────────┐    ┌─────────┐    ┌─────────┐
│ Agent A │ -> │ Agent B │ -> │ Agent C │
└─────────┘    └─────────┘    └─────────┘
```

**Routing logic**:
```python
return {
    "route": ["agent_a", "agent_b", "agent_c"],
    "payload": {"session": updated_session}
}
```

##### ParallelAgent

**ADK Definition** ([`parallel_agent.py:150`](src/google/adk/agents/parallel_agent.py:150)):
```python
parallel = ParallelAgent(
    name="parallel",
    sub_agents=[agent_a, agent_b, agent_c]
)
```

**Asya Compilation**: Fan-out/fan-in pattern

```
                ┌─────────┐
            ┌──>│ Agent A │──┐
            │   └─────────┘  │
┌──────┐   │   ┌─────────┐  │   ┌──────────┐
│Router│───┼──>│ Agent B │──┼──>│Aggregator│
└──────┘   │   └─────────┘  │   └──────────┘
            │   ┌─────────┐  │
            └──>│ Agent C │──┘
                └─────────┘
```

**Router actor**:
```python
async def handle_parallel_router(message: dict):
    """Fan-out to all sub-agents."""
    session = message["session"]

    # Send to all sub-agents with unique branches
    for agent_name in ["agent_a", "agent_b", "agent_c"]:
        yield {
            "route": [agent_name],
            "payload": {
                "session": session,
                "branch": f"parallel.{agent_name}",
                "aggregator_id": message["invocation_id"]
            }
        }
```

**Aggregator actor**:
```python
async def handle_parallel_aggregator(message: dict):
    """Wait for all sub-agents to finish."""
    aggregator_id = message["aggregator_id"]

    # Store result in Redis
    await redis.lpush(f"results:{aggregator_id}", message["event"])

    # Check if all done
    results = await redis.lrange(f"results:{aggregator_id}", 0, -1)
    if len(results) == 3:  # All 3 agents finished
        # Merge results and continue
        return {
            "route": ["gateway"],
            "payload": {"session": merge_sessions(results)}
        }
    else:
        # Wait for more results (no routing)
        return {"route": []}
```

##### LoopAgent

**ADK Definition** ([`loop_agent.py:51`](src/google/adk/agents/loop_agent.py:51)):
```python
loop = LoopAgent(
    name="loop",
    sub_agents=[agent_a, agent_b],
    max_iterations=5
)
```

**Asya Compilation**: Loop with exit condition

```
    ┌─────────────────────────┐
    │                         │
    v                         │
┌─────────┐    ┌─────────┐   │
│ Agent A │ -> │ Agent B │ ──┘
└─────────┘    └─────────┘
    │
    │ (escalate or max_iterations)
    v
┌─────────┐
│ Gateway │
└─────────┘
```

**Routing logic**:
```python
async def handle_agent_b(message: dict):
    """Last agent in loop - decide whether to continue."""
    session = message["session"]
    iteration = message.get("iteration", 0)

    # Run agent
    async for event in agent_b.run_async(context):
        yield event

    # Check exit conditions
    if event.actions.escalate or iteration >= 5:
        # Exit loop
        return {
            "route": ["gateway"],
            "payload": {"session": session}
        }
    else:
        # Continue loop
        return {
            "route": ["agent_a"],
            "payload": {
                "session": session,
                "iteration": iteration + 1
            }
        }
```

#### Unsupported: Custom Agents

Agents with custom `_run_async_impl()` logic - supported with compilation as asya flow:

```python
class MyCustomAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        # Complex custom logic
        if some_condition:
            async for event in sub_agent_a.run_async(ctx):
                yield event
        else:
            async for event in sub_agent_b.run_async(ctx):
                yield event
```

---

### 10. Implementation Examples

#### Example 1: Simple LlmAgent

**ADK Agent**:
```python
# agent.py
from google.adk import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool

root_agent = Agent(
    name="search_assistant",
    model="gemini-2.5-flash",
    instruction="You are a helpful assistant that can search the web.",
    tools=[GoogleSearchTool()]
)
```

**Asya Actor**:
```python
# actor_handler.py
from agent import root_agent
from services import get_artifact_service, get_session_service

async def handle_search_assistant(message: dict):
    """Actor handler - just yield events."""
    context = InvocationContext(
        artifact_service=get_artifact_service(),
        session_service=get_session_service(),
        session=Session.model_validate(message["session"]),
        agent=root_agent,
        invocation_id=message["invocation_id"]
    )

    async for event in root_agent.run_async(context):
        yield event

    yield {"type": "end"}
```

**Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: search-assistant-actor
spec:
  template:
    spec:
      containers:
      - name: actor
        image: asya-adk-actor:latest
        env:
          - name: ACTOR_HANDLER
            value: "actor_handler:handle_search_assistant"
          - name: ADK_ARTIFACT_SERVICE_TYPE
            value: "gcs"
          - name: ADK_ARTIFACT_SERVICE_BUCKET
            value: "my-artifacts"
        volumeMounts:
        - name: agent-code
          mountPath: /app/agent.py
          subPath: agent.py
        - name: actor-code
          mountPath: /app/actor_handler.py
          subPath: actor_handler.py
        - name: asya-runtime
          mountPath: /app/asya_runtime.py
          subPath: asya_runtime.py
      volumes:
      - name: agent-code
        configMap:
          name: search-assistant-agent
      - name: actor-code
        configMap:
          name: search-assistant-actor
      - name: asya-runtime
        configMap:
          name: asya-runtime  # Framework-provided
```

#### Example 2: Sequential Workflow

**ADK Agent**:
```python
# workflow.py
from google.adk.agents import SequentialAgent, Agent

planner = Agent(name="planner", instruction="Create a plan")
executor = Agent(name="executor", instruction="Execute the plan")
reviewer = Agent(name="reviewer", instruction="Review the results")

workflow = SequentialAgent(
    name="workflow",
    sub_agents=[planner, executor, reviewer]
)
```

**Asya Compilation**:

Three actors: `planner`, `executor`, `reviewer`

**Planner Actor**:
```python
async def handle_planner(message: dict):
    context = create_context(message)

    async for event in planner.run_async(context):
        yield event

    # Route to executor
    yield {
        "type": "end",
        "next_route": ["executor"]
    }
```

**Executor Actor**:
```python
async def handle_executor(message: dict):
    context = create_context(message)

    async for event in executor.run_async(context):
        yield event

    # Route to reviewer
    yield {
        "type": "end",
        "next_route": ["reviewer"]
    }
```

**Reviewer Actor**:
```python
async def handle_reviewer(message: dict):
    context = create_context(message)

    async for event in reviewer.run_async(context):
        yield event

    # Route to gateway (end of workflow)
    yield {
        "type": "end",
        "next_route": ["gateway"]
    }
```

---

### 11. Trade-offs & Design Decisions

#### Decision 1: Dual-Channel vs. Single-Channel

**Chosen**: Dual-channel (control via SQS, streaming via HTTP)

| Aspect | Dual-Channel | Single-Channel |
|--------|--------------|----------------|
| **Complexity** | Higher (two transports) | Lower (one transport) |
| **Scalability** | Better (streaming doesn't block control) | Worse (queue flooded) |
| **Latency** | Lower (direct HTTP for streaming) | Higher (queue overhead) |
| **Ordering** | Requires sequence numbers | Natural ordering |
| **Infrastructure** | Needs HTTP gateway | Just message queue |

**Rationale**: Real-time streaming is critical for chat UIs. Mixing high-frequency streaming with low-frequency control messages would flood queues and add latency.

#### Decision 2: Session in Message vs. Shared Store

**Chosen**: Session in message (with compression strategies)

| Aspect | Session in Message | Shared Store |
|--------|-------------------|--------------|
| **Simplicity** | Higher (self-contained) | Lower (fetch required) |
| **Latency** | Lower (no fetch) | Higher (DB roundtrip) |
| **Message size** | Larger (grows with conversation) | Smaller (just session_id) |
| **Fault tolerance** | Better (message has all context) | Worse (DB dependency) |
| **Consistency** | Easier (no distributed state) | Harder (cache invalidation) |

**Rationale**: Aligns with Asya's philosophy of self-contained messages. Compression strategies (artifact references, compaction) keep messages manageable.

#### Decision 3: Services from Environment vs. Message

**Chosen**: Services from environment (deployment-time config)

| Aspect | Environment | Message |
|--------|-------------|---------|
| **Message size** | Smaller (no configs) | Larger (configs in every message) |
| **Flexibility** | Lower (requires redeployment) | Higher (per-message configs) |
| **Security** | Better (secrets in env vars) | Worse (secrets in messages) |
| **Simplicity** | Higher (fail-fast at startup) | Lower (lazy initialization) |

**Rationale**: Most deployments use same services for all messages. Multi-tenancy handled via tenant_id in message, not different service configs.

#### Decision 4: Framework-Level Routing vs. User-Level

**Chosen**: Framework-level routing (user just yields events)

| Aspect | Framework Routing | User Routing |
|--------|------------------|--------------|
| **User code complexity** | Lower (just yield) | Higher (classify + route) |
| **Framework complexity** | Higher (classification logic) | Lower (pass-through) |
| **Consistency** | Better (centralized logic) | Worse (user errors) |
| **Flexibility** | Lower (fixed classification) | Higher (custom routing) |

**Rationale**: Simplifies user code dramatically. Classification logic is well-defined (partial vs. control) and unlikely to need customization.

#### Decision 5: Stateful vs. Stateless Gateway

**Chosen**: Stateful gateway (for MVP), with stateless option (for scale)

| Aspect | Stateful | Stateless (Redis) |
|--------|----------|-------------------|
| **Simplicity** | Higher (in-memory map) | Lower (Redis dependency) |
| **Scalability** | Lower (sticky sessions) | Higher (any gateway) |
| **Fault tolerance** | Lower (crash loses connections) | Higher (client reconnects) |
| **Latency** | Lower (no Redis hop) | Higher (~1-5ms) |

**Rationale**: Start simple with stateful gateway. Add Redis pub/sub when scaling beyond single gateway instance.

---

### 12. RFC Open Questions

#### 1. Event Ordering Guarantees

**Question**: How does ADK guarantee event ordering? Do we need to replicate this?

**Investigation needed**:
- Check if ADK uses sequence numbers
- Understand ordering guarantees between streaming and control events
- Determine if out-of-order delivery is acceptable

**Proposed solution**: Add `sequence_number` to all events, document best-effort ordering for streaming events.

#### 2. Backpressure and Flow Control

**Question**: What happens when actor generates events faster than gateway can send to client?

**Options**:
- Drop old streaming events (acceptable for audio/video)
- Buffer all events (memory risk)
- Backpressure to actor (complex)

**Decision**: Document as known limitation, implement dropping strategy for MVP.

#### 3. Partial Event Accumulation

**Question**: Should framework accumulate partial text, or should UI?

**ADK behavior**: Each partial event contains **accumulated** text:
```python
Event 1: "Hello"
Event 2: "Hello world"  # Accumulated
Event 3: "Hello world, how are you?"  # Accumulated
```

**Investigation needed**: Check A2UI protocol requirements.

**Proposed solution**: Follow A2UI protocol specification.

#### 4. Error Handling in Streaming

**Question**: How does user know if actor crashes mid-stream?

**Scenario**:
```
Actor yields:
1. Event A (partial=True) → Sent to user ✓
2. Event B (partial=True) → Sent to user ✓
3. [Actor crashes]
4. No "end" event sent
```

**Proposed solution**: Sidecar detects actor crash, sends error event to gateway.

#### 5. Multi-Agent Streaming

**Question**: How to display interleaved streams from parallel agents?

**ADK behavior**: Uses `branch` field ([`parallel_agent.py:42`](src/google/adk/agents/parallel_agent.py:42)) to separate parallel agents.

**Proposed solution**: Include `branch` in streaming events, UI separates by branch.

#### 6. Session Persistence During Streaming

**Question**: Should partial events be persisted if actor crashes?

**ADK behavior**: Partial events are **not** saved to session ([`runners.py:829`](src/google/adk/runners.py:829)).

**Decision**: Follow ADK behavior - partial events are ephemeral.

#### 7. Compilation of Custom Flows

**Question**: How to handle custom `_run_async_impl()` logic?

**Decision**: Not supported initially. Document limitation. Users must refactor to use built-in agents or accept single-actor deployment.

#### 8. Conversation State Size for Coding Agents

**Question**: Coding agents accumulate large context (files, diffs, error traces). How to manage envelope size?

**Considerations**:
- Coding conversations can exceed SQS 256 KB limit quickly
- Full file contents vs references to workspace files
- Should workspace state be part of envelope or external?

**Proposed approach**:
- Envelope contains conversation history + references (file paths, commit SHAs)
- Actual file contents fetched by actor from mounted workspace or object storage
- Workspace state is external; envelope contains pointers

#### 9. Tool Execution Model

**Question**: Should tools be local functions, remote actors, or hybrid?

**Trade-offs**:

| Model | Latency | Scalability | Isolation |
|-------|---------|-------------|-----------|
| Local functions | Low (~ms) | Limited to actor resources | None |
| Remote actors | High (~100ms+) | Independent scaling | Full |
| Hybrid | Varies | Best of both | Partial |

**Proposed approach**: Hybrid model where:
- Fast, simple tools (file read, shell exec) run locally within actor
- Expensive, shared tools (LLM calls, embeddings, search) are separate actors
- Tool classification defined in agent configuration

---

### 13. References

#### ADK Source Code

- **Runner**: [`src/google/adk/runners.py:102`](src/google/adk/runners.py:102)
- **BaseAgent**: [`src/google/adk/agents/base_agent.py:85`](src/google/adk/agents/base_agent.py:85)
- **LlmAgent**: [`src/google/adk/agents/llm_agent.py:183`](src/google/adk/agents/llm_agent.py:183)
- **SequentialAgent**: [`src/google/adk/agents/sequential_agent.py:47`](src/google/adk/agents/sequential_agent.py:47)
- **ParallelAgent**: [`src/google/adk/agents/parallel_agent.py:150`](src/google/adk/agents/parallel_agent.py:150)
- **LoopAgent**: [`src/google/adk/agents/loop_agent.py:51`](src/google/adk/agents/loop_agent.py:51)
- **Session**: [`src/google/adk/sessions/session.py:27`](src/google/adk/sessions/session.py:27)
- **Event**: [`src/google/adk/events/event.py:30`](src/google/adk/events/event.py:30)
- **EventActions**: [`src/google/adk/events/event_actions.py:50`](src/google/adk/events/event_actions.py:50)
- **LlmResponse**: [`src/google/adk/models/llm_response.py:28`](src/google/adk/models/llm_response.py:28)
- **BaseLlmFlow**: [`src/google/adk/flows/llm_flows/base_llm_flow.py:108`](src/google/adk/flows/llm_flows/base_llm_flow.py:108)
- **InvocationContext**: [`src/google/adk/agents/invocation_context.py:98`](src/google/adk/agents/invocation_context.py:98)
- **Event Compaction**: [`src/google/adk/apps/compaction.py`](src/google/adk/apps/compaction.py)

#### Asya Documentation

- **Actor-to-Actor Protocol**: https://github.com/deliveryhero/asya/blob/main/docs/architecture/protocols/actor-actor.md
- **Flows Example**: https://github.com/deliveryhero/asya/blob/main/examples/flows/if_mutations_in_branches.py
- **Compiled Routers**: https://github.com/deliveryhero/asya/blob/main/examples/flows/compiled/if_mutations_in_branches/routers.py

#### A2A Protocol

- **A2A Specification**: https://a2a-protocol.org/latest/specification/
- **A2A Definitions**: https://a2a-protocol.org/latest/definitions/
- **A2A GitHub**: https://github.com/a2aproject/A2A
- **A2A Python SDK**: https://github.com/a2aproject/a2a-python
- **Linux Foundation Announcement**: https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project

#### AG-UI Protocol

- **AG-UI Documentation**: https://docs.ag-ui.com/
- **AG-UI GitHub**: https://github.com/ag-ui-protocol/ag-ui
- **CopilotKit Integration**: https://docs.copilotkit.ai/ag-ui-protocol
- **Event Types Guide**: https://www.copilotkit.ai/blog/master-the-17-ag-ui-event-types-for-building-agents-the-right-way

#### A2UI Protocol

- **A2UI Official Site**: https://a2ui.org/
- **A2UI GitHub**: https://github.com/google/A2UI
- **Google Announcement**: https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/

#### External References

- **ADK Documentation**: https://google.github.io/adk-docs
- **ADK GitHub**: https://github.com/google/adk-python
- **Asya GitHub**: https://github.com/deliveryhero/asya
- **MCP (Model Context Protocol)**: https://modelcontextprotocol.io/

#### Additional Protocol Standards (Research)

Feasibility research tracked in beads:

| Bead | Protocol | Priority | Description |
|------|----------|----------|-------------|
| `asya-8sa` | AGNTCY | P3 | Cisco/LF agent discovery, identity, observability |
| `asya-3d6` | AAIF | P4 | Linux Foundation standards (MCP host, AGENTS.md) |
| `asya-e5s` | ANP/OASF | P4 | Decentralized protocols (P2P, DID-based identity) |

**Resources:**
- **AAIF (Agentic AI Foundation)**: https://lfaidata.foundation/projects/aaif/
- **AGNTCY**: https://agntcy.org/
- **Agent Skills**: https://github.com/anthropics/anthropic-cookbook/tree/main/skills

---

### Next Steps

1. **Implement A2A endpoints**: Add Agent Card, message, and task endpoints to Gateway
2. **Validate core architecture**: Build prototype with single LlmAgent actor
3. **Test session compression**: Measure message sizes with real conversations
4. **Implement framework runtime**: Create `asya_runtime.py` with event classification
5. **Build A2A streaming**: Implement `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` via SSE
6. **Compile SequentialAgent**: Validate multi-actor workflows
7. **Test human-in-the-loop**: Validate `input_required` state with A2A clients
8. **Performance testing**: Measure latency, throughput, scalability
9. **A2A compliance testing**: Test interoperability with A2A Python SDK
10. **Documentation**: User guide for deploying ADK agents on Asya via A2A


---
## Notes

## Session State Strategy (Concluded 2026-01-28)

**Decision: Message-truth by default with layered complexity**

### Core Strategy
1. **Message-truth by default** - session carried in envelope payload
2. **Binary protocol (TLV)** - ~2.5x effective capacity vs JSON
3. **Artifact references mandatory** - media always in S3/GCS, never inline
4. **External state ONLY for fan-out/fan-in** - scoped to aggregator actor

### Why This Works
- SQS limit is 1 MiB (not 256KB) - most conversations fit
- Binary serialization adds ~40-60% compression
- Media offloaded to object storage keeps messages small
- Only parallel execution needs coordination state

### Priorities Achieved
- ✅ Simplicity: No external session store for sequential flows
- ✅ Low latency: No DB roundtrips for most operations
- ✅ Scale: Binary protocol + 1MiB limit handles 200+ turn conversations
- ✅ Durability: Media persisted to S3/GCS, messages are self-contained

### Research Beads Created
- asya-o42: Queue size limits across transports
- asya-6j2: Binary protocol design (TLV + Marshal)
- asya-zpl: Stateful actor for fan-out/fan-in
- asya-z1o: Media storage abstraction (fsspec)


---
_Migrated from beads `asya-bi8`_
