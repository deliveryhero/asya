# Agent A2A Integration: Missing Functionality

## P0 — Blocking

### 1. Pause metadata not returned in A2A GetTask or status events

**Current state**: When a task pauses, the A2A status transitions to
`input_required`. But the pause metadata (prompt text, required fields with
types, validation rules) is NOT included in the status event or GetTask
response. External agents see "input required" but don't know WHAT input.

**Files**:
- `src/asya-gateway/internal/a2a/executor.go` — GetTask builds response
  without PauseMetadata
- `src/asya-gateway/internal/store/models.go` — PauseMetadata stored in DB
  but not surfaced

**What's needed**:
- A2A status event includes `metadata.input_schema` with JSON Schema
  describing required fields
- GetTask response includes `status.metadata.prompt` and `status.metadata.fields`
- External agents can auto-generate input prompts from schema

**Impact**: This is the single biggest gap for agent integration. Without it,
pause/resume is unusable by automated agents — they can't programmatically
determine what to ask.

### 2. No multi-turn conversation within a task context

**Current state**: Each A2A `message/send` creates a new task. Clients cannot
send follow-up messages to refine a running task. The only mid-task
interaction is pause/resume.

**Files**:
- `src/asya-gateway/internal/a2a/executor.go:66` — new message always creates
  new task (or resumes paused task)
- No "append message to running task" path

**What's needed**:
- A2A `message/send` with existing `task_id` appends to conversation
- Gateway routes follow-up message to running pipeline as steering input
- Or: document that Asya uses request/response model, not conversational
  (each task is a single turn; multi-turn happens at the calling agent level)

---

## P1 — Important

### 3. Agent Card capabilities not per-skill

**Current state**: Agent Card declares global capabilities (`streaming: true`,
`pushNotifications: false`). All skills appear to have the same capabilities.

**Files**:
- `src/asya-gateway/internal/a2a/agent_card_producer.go:50-53` — hard-coded
  global capabilities

**What's needed**:
- Per-skill capabilities: skill X supports streaming + pause/resume;
  skill Y is synchronous-only
- External agents can decide which integration pattern to use per skill
- Capability flags: `streaming`, `pause_resume`, `estimated_duration`

### 4. No A2A push notifications

**Current state**: Declared as `false` in Agent Card. Clients must poll or
hold SSE connections open.

**Files**:
- `src/asya-gateway/internal/a2a/agent_card_producer.go:53` —
  `PushNotifications: false`

**What's needed**:
- Webhook-based push notifications for task completion
- External agents register callback URL; gateway POSTs status updates
- Critical for long-running pipelines where holding SSE is impractical

### 5. No task history / conversation context across tasks

**Current state**: `context_id` groups tasks but there's no API to retrieve
conversation history within a context. External agents can't say "continue
our previous research" without re-sending all prior context.

**Files**:
- `src/asya-gateway/internal/a2a/executor.go` — context_id used for filtering
  in tasks/list but no history aggregation

**What's needed**:
- `GET /a2a/` with `tasks/list` filtered by context_id returns ordered history
- Optional: conversation summary endpoint that compacts prior task results

### 6. No authenticated extended card per agent identity

**Current state**: Extended agent card (`agent/authenticatedExtendedCard`)
returns same enriched card for all authenticated clients.

**What's needed**:
- Per-client card: show only skills the client is authorized to use
- OAuth scope-filtered skill list
- Different capabilities based on client trust level

---

## P2 — Nice to Have

### 7. No A2A server-to-server delegation

**Current state**: Asya is an A2A server only. It can't call other A2A agents
as part of a pipeline.

**What's needed**:
- `x-a2a-call` crew actor that acts as A2A client
- Flow DSL: `p = await external_agent(p)  # asya: a2a, url=https://...`
- Enables Asya-to-Asya federation and hybrid pipelines

### 8. No Agent Card auto-generation from flows

**Current state**: Agent Card skills derived from gateway tool registry
(ConfigMap YAML). Not automatically generated from compiled flows.

**What's needed**:
- Flow compiler outputs Agent Card skill definitions
- Includes input/output modes, examples, tags from flow metadata
- Gateway merges compiled skill definitions into Agent Card
