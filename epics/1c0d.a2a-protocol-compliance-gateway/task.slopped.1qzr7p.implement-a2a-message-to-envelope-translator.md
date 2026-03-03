---
title: Implement A2A message-to-envelope translator
priority: 2 # medium
type: task
dependencies: [1c0d/1qcmsr]
---

## Objective

Rewrite the `MessageToPayload` function in `internal/a2a/translator.go` to comply
with RFC Section 5.2 (Message-to-Envelope Translation). The current implementation
uses synthetic underscore-prefixed fields (`_a2a_text`, `_a2a_files`) and does not
construct the `payload.a2a.task` namespace. The new implementation uses `a2a-go`
types (from task `1c0d/1qcmsr`) and produces the canonical payload structure defined
in the RFC.

## Scope

### 1. Rewrite `messageToPayload()` in `internal/a2a/translator.go`

Replace the current `MessageToPayload` function (exported, uses hand-rolled types)
with `messageToPayload()` (unexported, uses `a2a-go` types). The function signature
should accept an `a2a.Message` (from the `a2a-go` library), task ID, and context ID,
and return a `map[string]any` payload.

### 2. Payload construction rules (RFC Section 5.2)

The envelope payload contains two distinct areas:
- `payload.a2a.task` -- A2A Task object (history, artifacts, metadata). Mirrors the
  A2A `Task` proto exactly. Managed by the gateway and crew actors.
- Everything else at payload root -- Actor-custom fields extracted from the Message
  parts for actor consumption.

**Rule 1 -- Always first**: Initialize `payload.a2a.task` with `id`, `context_id`,
and append the full A2A Message to `payload.a2a.task.history[]`.

```json
{
  "a2a": {
    "task": {
      "id": "task-uuid",
      "context_id": "ctx-uuid",
      "history": [{ "message_id": "m-001", "role": "user", "parts": [...] }],
      "metadata": { "skill": "analyze-doc" }
    }
  }
}
```

**Rule 2 -- Single data Part**: If the Message has exactly one `data` Part (and no
other part types), unwrap `data.Value` and merge its keys at the payload root. This
is the common case for structured API calls.

```json
parts: [{ data: { query: "...", depth: 3 } }]
  -> payload: { a2a: { task: { ... } }, query: "...", depth: 3 }
```

**Rule 3 -- Text-only Parts**: If all Parts are `text` type, concatenate them with
`\n` and store as `payload.query` (conventional field name for text-based skills).

```json
parts: [{ text: "Analyze this" }]
  -> payload: { a2a: { task: { ... } }, query: "Analyze this" }
```

**Rule 4 -- Mixed or multi-part**: The full A2A Message with all parts is preserved
in `payload.a2a.task.history`. Actor-facing extraction is best-effort: if there is a
single `data` Part among the parts, merge it at root. Otherwise, actors read from
`payload.a2a.task.history[-1].parts` directly.

### 3. No synthetic underscore-prefixed fields (RFC Section 5.2)

The gateway does NOT create `_a2a_files`, `_a2a_text`, or any underscore-prefixed
convenience fields. The current implementation creates both `_a2a_text` and
`_a2a_files` -- these must be removed entirely. The canonical A2A data lives in
`payload.a2a.task` and actors that need multi-part awareness read from there.

### 4. Header stamping (RFC Section 5.6)

When the translator constructs the envelope (or when the caller assembles the
envelope from the translated payload), the following headers must be set:

```json
{
  "headers": {
    "x-asya-a2a-task-id": "task-uuid",
    "x-asya-a2a-context-id": "ctx-uuid"
  }
}
```

These headers provide lightweight access for the sidecar, which must not parse
payload contents. The sidecar uses `x-asya-a2a-task-id` for progress reporting
(`POST /mesh/{id}/progress`).

If the translator itself does not set headers (because envelope construction happens
in the caller), document clearly that the caller is responsible for stamping these
headers and provide a helper function or constants for the header keys.

### 5. Inbound blob handling (RFC Section 5.2)

If a client sends a Message with `raw` (binary) Parts, the gateway must externalize
them before dispatching the envelope:

1. Write the `raw` content to external storage via state proxy.
2. Replace the `raw` Part with a `url` Part referencing the stored content.
3. This protects the pipeline from queue size limit violations (SQS: 256KB).

Small `text` and `data` Parts in Messages are stored inline in
`payload.a2a.task.history` (they are typically prompt-sized).

For the initial implementation, if state proxy integration is not yet available,
reject Messages with `raw` Parts with an appropriate error and add a TODO for
state proxy integration.

### 6. Update callers

Update `internal/a2a/handler.go` where `MessageToPayload` is currently called
(in `resolveAndCreateTask` and `handleResume`). The callers need to:
- Pass the task ID and context ID to the new function
- Set the `x-asya-a2a-*` headers on the envelope

Also update `TaskToA2ATask` and `TaskUpdateToSSEEvents` in the same file if they
reference hand-rolled types that have been replaced by `a2a-go` types.

### 7. Unit tests (RFC Section 15.1)

Create or update `src/asya-gateway/internal/a2a/translator_test.go` covering:

- **Single data Part**: Unwrap at root, `a2a.task` namespace present with history
- **Text-only Parts**: Concatenated with `\n` as `payload.query`
- **Mixed parts**: `data` Part merged at root, text and file parts preserved in
  history only
- **Multi-part text**: Multiple text Parts concatenated correctly
- **No synthetic fields**: Verify `_a2a_text` and `_a2a_files` are NOT present in
  output
- **History construction**: Full A2A Message appended to `payload.a2a.task.history[]`
- **A2A task namespace**: `payload.a2a.task.id` and `payload.a2a.task.context_id`
  match provided IDs
- **Empty parts**: Edge case with zero parts (should error or produce minimal payload)
- **Raw Part rejection**: If raw Part handling is deferred, verify appropriate error

## Files

- `src/asya-gateway/internal/a2a/translator.go` -- rewrite `MessageToPayload`
- `src/asya-gateway/internal/a2a/translator_test.go` -- update/rewrite tests
- `src/asya-gateway/internal/a2a/handler.go` -- update callers to use new signature

## Dependencies

- **T2** (`1c0d/1qcmsr`): Needs `a2a-go` types (`a2a.Message`, `a2a.Part`, etc.)
  to be available. The state mapping functions are not directly used here, but the
  `a2a-go` import and type cleanup must be done first.

## Acceptance Criteria

- `messageToPayload()` produces the canonical `payload.a2a.task` structure per RFC.
- No `_a2a_text`, `_a2a_files`, or other underscore-prefixed synthetic fields in
  output.
- Header keys `x-asya-a2a-task-id` and `x-asya-a2a-context-id` are stamped on the
  envelope (either by the translator or documented caller responsibility).
- All unit tests pass covering the 4 payload construction rules.
- `go build ./...` succeeds with updated callers.
