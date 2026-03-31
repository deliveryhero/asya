# Long-Running Checkpointed: Missing Functionality

## P0 — Blocking

### 1. Pause metadata not exposed via A2A GetTask

**Current state**: `x-pause` stores pause metadata (prompt text, required
fields with types) in the checkpoint. Gateway receives it via sidecar
progress report. But `GetTask()` does NOT return this metadata to clients.

**Files**:
- `src/asya-crew/asya_crew/pause.py` — writes `_pause_metadata` with prompt
  and field schemas
- `src/asya-gateway/internal/a2a/executor.go` — `GetTask()` returns status
  but not pause metadata fields
- `src/asya-gateway/internal/store/models.go` — `PauseMetadata` stored in DB

**What's needed**:
- `GetTask()` response includes pause metadata when status is `input_required`
- A2A task status message includes structured schema for required input
- Clients (Claude Code, Goose, etc.) can render the right prompt to the user

**Impact**: Without this, external agents don't know WHAT to ask the human.
They see `input_required` but not "please approve the experiment plan by
providing: approved (bool), feedback (string), budget_override (number)."

---

## P1 — Important

### 2. No pause metadata schema validation

**Current state**: `ASYA_PAUSE_METADATA` is free-form JSON. x-resume accepts
any payload without validating against the declared fields.

**Files**:
- `src/asya-crew/asya_crew/resume.py` — merges input without type checking
- `src/asya-crew/asya_crew/pause.py` — no schema validation on metadata

**What's needed**:
- x-resume validates input against pause metadata field definitions
- Type coercion (string "true" -> boolean) for UI-submitted values
- Required field enforcement (reject resume if field missing)

### 3. No checkpoint listing or management API

**Current state**: Checkpointed envelopes sit in S3 under `paused/{msg_id}.json`.
No API to list all paused tasks, inspect their state, or bulk-resume.

**What's needed**:
- `GET /mesh/paused` — list all paused tasks with their metadata
- `GET /mesh/paused/{id}` — inspect checkpoint content
- `DELETE /mesh/paused/{id}` — abandon a paused task
- Dashboard view for human reviewers

### 4. No timeout extension on resume

**Current state**: x-resume accepts `x-asya-resume-timeout` to set remaining
budget, but there's no way to EXTEND the original SLA beyond what was
remaining when the task paused.

**Files**:
- `src/asya-crew/asya_crew/resume.py` — computes deadline from remaining
  seconds only

**What's needed**:
- Resume with additional time: "grant 2 more hours for execution phase"
- Or: per-phase SLA (different timeout for pre-human vs post-human steps)

### 5. No notification on pause

**Current state**: Paused task emits an SSE event, but there's no webhook
or push notification to alert a human reviewer that their input is needed.

**What's needed**:
- Configurable pause notification: webhook URL, Slack channel, email
- Reminder escalation: "task paused for >24h, ping reviewer again"
- Integration point for external notification systems

---

## P2 — Nice to Have

### 6. No partial progress persistence for long actors

**Current state**: If a 2-hour `literature_review` actor pod dies at 1h50m,
all work is lost. The queue retries from scratch.

**What's needed**:
- Intra-actor checkpointing: actor periodically saves progress to state-proxy
- On restart, actor resumes from last checkpoint
- This is actor-level responsibility, but a framework pattern would help

### 7. No pipeline progress dashboard

**Current state**: FLY events stream per-actor progress. But for a 7-step
pipeline running over days, there's no consolidated view showing
"step 3 of 7, paused waiting for human since 2 days ago."

**What's needed**:
- Pipeline-level progress derived from route.prev/curr/next
- Gateway endpoint: `GET /mesh/{id}/pipeline` returning step statuses
- Estimated time remaining based on historical step durations
