# PR3: Sidecar Changes — Execution Plan

## Summary

Three changes to `src/asya-sidecar/` (~200 LOC net), making the sidecar work with
the new mesh-api from PR1. All changes are backward-compatible: if the envelope
header is missing, env var is used; if the new `/events` endpoint 404s, old
endpoints are used.

**Files modified:**

| File | Change | LOC delta |
|---|---|---|
| `src/asya-sidecar/pkg/envelopes/envelope.go` | Add `HeaderGatewayURL` constant | +3 |
| `src/asya-sidecar/internal/config/config.go` | No changes (ASYA_GATEWAY_URL remains as fallback) | 0 |
| `src/asya-sidecar/internal/progress/reporter.go` | New unified `PostEvent` + `CheckMessage` methods, backward compat fallback | +80 |
| `src/asya-sidecar/internal/router/router.go` | Read gateway URL from envelope header, pre-flight check, use `PostEvent` | +50, -30 |
| `src/asya-sidecar/internal/progress/reporter_test.go` | Tests for `PostEvent`, `CheckMessage`, fallback behavior | +120 |
| `src/asya-sidecar/internal/router/router_test.go` | Tests for envelope header URL, pre-flight cancel/pause, backward compat | +100 |

**Depends on:** PR1 merged (mesh-api must exist for integration testing). Unit
tests are self-contained with httptest mocks.

---

## Change 1: Read Gateway URL from Envelope Header

### 1.1 New constant in envelope.go

**File:** `src/asya-sidecar/pkg/envelopes/envelope.go`

Add header constant alongside existing ones:

```go
// Mesh-status header constants for stealth mode control
const (
	HeaderMeshStatus   = "x-asya-mesh-status"
	MeshStatusOff      = "off"
	HeaderFirstAttempt = "x-asya-first-attempt"
	HeaderGatewayURL   = "x-asya-gateway-url"
)
```

### 1.2 Per-envelope gateway URL resolution in router.go

**File:** `src/asya-sidecar/internal/router/router.go`

Add a helper method that resolves the gateway URL for a given envelope. The
envelope header takes precedence; the Router's configured `gatewayURL` (from
`ASYA_GATEWAY_URL` env var) is the fallback.

```go
// resolveGatewayURL returns the gateway URL for this envelope.
// Envelope header x-asya-gateway-url takes precedence over the env var fallback.
func (r *Router) resolveGatewayURL(msg *envelopes.Envelope) string {
	if msg.Headers != nil {
		if raw, ok := msg.Headers[envelopes.HeaderGatewayURL]; ok {
			if s, ok := raw.(string); ok && s != "" {
				return s
			}
		}
	}
	return r.gatewayURL
}
```

### 1.3 Use per-envelope URL in isMeshStatusEnabled

Currently `isMeshStatusEnabled` checks `r.progressReporter == nil`. The
progressReporter is only created when `cfg.GatewayURL != ""` (i.e. env var set).
With envelope headers, an envelope may carry a gateway URL even when the env var
is empty.

**Current code** (router.go lines 179-190):
```go
func (r *Router) isMeshStatusEnabled(msg *envelopes.Envelope) bool {
	if r.progressReporter == nil {
		return false
	}
	if v, ok := msg.Headers[envelopes.HeaderMeshStatus]; ok {
		if s, ok := v.(string); ok && s == envelopes.MeshStatusOff {
			slog.Debug("Skipping mesh status reporting: x-asya-mesh-status=off", "id", msg.ID)
			return false
		}
	}
	return msg.ID != ""
}
```

**New code:**
```go
func (r *Router) isMeshStatusEnabled(msg *envelopes.Envelope) bool {
	if r.resolveGatewayURL(msg) == "" {
		return false
	}
	if v, ok := msg.Headers[envelopes.HeaderMeshStatus]; ok {
		if s, ok := v.(string); ok && s == envelopes.MeshStatusOff {
			slog.Debug("Skipping mesh status reporting: x-asya-mesh-status=off", "id", msg.ID)
			return false
		}
	}
	return msg.ID != ""
}
```

This change means mesh reporting is enabled if **either** the envelope header or
the env var provides a gateway URL. An envelope from a new mesh-api dispatcher
will always have the header, even if the actor was deployed without
`ASYA_GATEWAY_URL`.

### 1.4 Pass per-envelope URL to Reporter methods

The `Reporter` currently stores `gatewayURL` at construction time. Rather than
rebuilding a Reporter per envelope, we add an optional URL override parameter to
the new unified `PostEvent` method (Change 2) and to the existing methods during
the transition.

**Approach:** Add a `getReporter` helper to Router that returns a reporter
configured with the per-envelope URL:

```go
// getReporter returns a progress.Reporter for the given envelope.
// If the envelope carries x-asya-gateway-url, a reporter targeting that URL is
// returned. Otherwise falls back to the router's default reporter (which may be nil).
func (r *Router) getReporter(msg *envelopes.Envelope) *progress.Reporter {
	envelopeURL := r.resolveGatewayURL(msg)
	if envelopeURL == "" {
		return nil
	}
	// If the envelope URL matches the default, reuse the existing reporter
	// (avoids allocating a new http.Client per message)
	if r.progressReporter != nil && r.progressReporter.GetGatewayURL() == envelopeURL {
		return r.progressReporter
	}
	// Envelope-specific URL: create a short-lived reporter
	return progress.NewReporter(envelopeURL, r.actorName)
}
```

Then replace all `r.progressReporter.ReportProgress(...)` calls with
`r.getReporter(msg).ReportProgress(...)` (guarded by `isMeshStatusEnabled` which
already checks for empty URL).

**Call sites to update in router.go** (each currently uses `r.progressReporter`):

1. **Line ~678** (`handleSuccessResponse`): `r.progressReporter.ReportProgress(...)` -> `r.getReporter(msg).ReportProgress(...)`
2. **Line ~696** (`handleSuccessResponse` fanout): `r.progressReporter.CreateMesh(...)` -> `r.getReporter(msg).CreateMesh(...)`
3. **Line ~738** (`handleSuccessResponse` pause): `r.progressReporter.ReportProgress(...)` -> `r.getReporter(msg).ReportProgress(...)`
4. **Line ~818** (`ProcessMessage` received status): `r.progressReporter.ReportProgress(...)` -> `r.getReporter(msg).ReportProgress(...)`
5. **Line ~851** (`ProcessMessage` processing status): `r.progressReporter.ReportProgress(...)` -> `r.getReporter(msg).ReportProgress(...)`
6. **Line ~882** (`ProcessMessage` FLY callback): `r.progressReporter.ForwardFly(...)` -> `r.getReporter(msg).ForwardFly(...)`
7. **Line ~237** (`processEndActorEnvelope` timeout): `r.progressReporter.ReportFinalError(...)` -> `r.getReporter(msg).ReportFinalError(...)`
8. **Line ~262** (`processEndActorEnvelope` final): `r.reportFinalStatusWithMessage(...)` -> needs envelope-aware URL
9. **Line ~1214** (`handleSLAExpiry`): `r.progressReporter.ReportFinalError(...)` -> `r.getReporter(&msg).ReportFinalError(...)`
10. **Line ~1489** (`reportFinalStatusWithMessage`): uses `r.gatewayURL` directly for URL construction -> use `r.resolveGatewayURL(msg)`

For `reportFinalStatusWithMessage` (line 1489), change:
```go
// Current:
url := fmt.Sprintf("%s/mesh/%s/final", r.gatewayURL, msg.ID)
// New:
url := fmt.Sprintf("%s/mesh/%s/final", r.resolveGatewayURL(msg), msg.ID)
```

Similarly for the deprecated `reportFinalStatus` (line 1621) — update to accept envelope or leave as-is since it's deprecated and only used in legacy code paths.

### 1.5 Set X-Asya-Envelope-ID header on all outgoing requests

For Ingress consistent hash routing, all HTTP requests to the gateway must carry
the `X-Asya-Envelope-ID` header.

**File:** `src/asya-sidecar/internal/progress/reporter.go`

Add the header to every outgoing request. Update `ReportProgress`, `ForwardFly`,
`ReportFinalError`, `CreateMesh`, and the new `PostEvent`/`CheckMessage` methods
(Change 2).

```go
// setEnvelopeHeader adds the X-Asya-Envelope-ID header for Ingress hash routing.
func setEnvelopeHeader(req *http.Request, envelopeID string) {
	if envelopeID != "" {
		req.Header.Set("X-Asya-Envelope-ID", envelopeID)
	}
}
```

Call `setEnvelopeHeader(req, id)` after creating each `http.Request` in every
Reporter method. This requires threading the envelope ID through to methods that
currently don't have it (e.g. `ReportFinalError`, `CheckHealth`). For existing
methods, add the ID parameter; for `CheckHealth` it's not needed (no envelope
context).

---

## Change 2: Unified Event POST

### 2.1 New types in reporter.go

**File:** `src/asya-sidecar/internal/progress/reporter.go`

```go
// EventType distinguishes status updates from FLY events in the unified endpoint.
type EventType string

const (
	EventTypeStatus EventType = "status"
	EventTypeFly    EventType = "fly"
)

// MeshEvent is the payload for POST /api/v1/mesh/{id}/events.
type MeshEvent struct {
	Type   EventType       `json:"type"`
	Status string          `json:"status,omitempty"` // for type=status: "running", "succeeded", "failed"
	Data   json.RawMessage `json:"data,omitempty"`   // event-specific payload
}
```

### 2.2 PostEvent method with backward compatibility fallback

```go
// PostEvent sends an event to the mesh-api unified endpoint.
// Falls back to legacy endpoints (/mesh/{id}/progress, /mesh/{id}/fly,
// /mesh/{id}/final) if the new endpoint returns 404.
func (r *Reporter) PostEvent(ctx context.Context, id string, event MeshEvent) error {
	if id == "" {
		return nil
	}

	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal event: %w", err)
	}

	// Try new unified endpoint first
	url := fmt.Sprintf("%s/api/v1/mesh/%s/events", r.gatewayURL, id)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	setEnvelopeHeader(req, id)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		slog.Warn("Failed to POST event to mesh-api", "id", id, "error", err)
		return r.postEventLegacyFallback(ctx, id, event, payload)
	}
	defer func() { _ = resp.Body.Close() }()

	// 404 = old gateway, fall back to legacy endpoints
	if resp.StatusCode == http.StatusNotFound {
		slog.Debug("Mesh-api /events returned 404, falling back to legacy endpoints", "id", id)
		return r.postEventLegacyFallback(ctx, id, event, payload)
	}

	if resp.StatusCode >= 300 {
		return fmt.Errorf("mesh-api returned status %d for event POST", resp.StatusCode)
	}

	return nil
}
```

### 2.3 Legacy fallback method

```go
// postEventLegacyFallback routes to the old /mesh/{id}/progress, /mesh/{id}/fly,
// or /mesh/{id}/final endpoints based on event type and status.
func (r *Reporter) postEventLegacyFallback(ctx context.Context, id string, event MeshEvent, payload []byte) error {
	switch event.Type {
	case EventTypeFly:
		return r.ForwardFly(ctx, id, event.Data)
	case EventTypeStatus:
		// Terminal statuses go to /final, others to /progress
		if event.Status == "succeeded" || event.Status == "failed" {
			url := fmt.Sprintf("%s/mesh/%s/final", r.gatewayURL, id)
			req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
			if err != nil {
				return err
			}
			req.Header.Set("Content-Type", "application/json")
			setEnvelopeHeader(req, id)
			resp, err := r.httpClient.Do(req)
			if err != nil {
				return err
			}
			defer func() { _ = resp.Body.Close() }()
			if resp.StatusCode >= 300 {
				return fmt.Errorf("legacy /final returned status %d", resp.StatusCode)
			}
			return nil
		}
		// Non-terminal status -> /progress (existing method handles retries)
		var update ProgressUpdate
		if err := json.Unmarshal(event.Data, &update); err != nil {
			return r.ReportProgress(ctx, id, update)
		}
		return r.ReportProgress(ctx, id, update)
	default:
		return fmt.Errorf("unknown event type: %s", event.Type)
	}
}
```

### 2.4 Update router.go call sites to use PostEvent

Replace the three separate POST patterns in router.go with unified `PostEvent`:

**A) Progress reporting** (currently `ReportProgress`)

In `ProcessMessage` where `ReportProgress` is called for "received" and
"processing" statuses, replace with:

```go
// Current:
_ = r.progressReporter.ReportProgress(ctx, msg.ID, progress.ProgressUpdate{...})

// New:
reporter := r.getReporter(msg)
updateData, _ := json.Marshal(progress.ProgressUpdate{...})
_ = reporter.PostEvent(ctx, msg.ID, progress.MeshEvent{
	Type:   progress.EventTypeStatus,
	Status: "running",
	Data:   updateData,
})
```

**B) FLY forwarding** (currently `ForwardFly`)

In the `onUpstream` callback:

```go
// Current:
r.progressReporter.ForwardFly(ctx, msg.ID, payload)

// New:
reporter := r.getReporter(msg)
reporter.PostEvent(ctx, msg.ID, progress.MeshEvent{
	Type: progress.EventTypeFly,
	Data: payload,
})
```

**C) Final status reporting** (currently `reportFinalStatusWithMessage`)

Replace the direct HTTP POST in `reportFinalStatusWithMessage`:

```go
// Current:
url := fmt.Sprintf("%s/mesh/%s/final", r.gatewayURL, msg.ID)
req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payloadBytes))

// New:
reporter := r.getReporter(msg)
return reporter.PostEvent(ctx, msg.ID, progress.MeshEvent{
	Type:   progress.EventTypeStatus,
	Status: status, // "succeeded" or "failed"
	Data:   payloadBytes,
})
```

This collapses `reportFinalStatusWithMessage` significantly — all the URL
construction and HTTP client code moves into `PostEvent`. The function still
builds the `finalPayload` map, marshals it, then delegates to `PostEvent`.

**D) ReportFinalError** (currently a direct POST to /final)

Replace with:

```go
func (r *Reporter) ReportFinalError(ctx context.Context, taskID, errorMsg string) error {
	finalPayload := map[string]interface{}{
		"id":        taskID,
		"status":    "failed",
		"error":     errorMsg,
		"timestamp": time.Now().Format(time.RFC3339),
	}
	data, err := json.Marshal(finalPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal final error: %w", err)
	}
	return r.PostEvent(ctx, taskID, MeshEvent{
		Type:   EventTypeStatus,
		Status: "failed",
		Data:   data,
	})
}
```

---

## Change 3: Pre-Flight Check

### 3.1 New CheckMessage method in reporter.go

**File:** `src/asya-sidecar/internal/progress/reporter.go`

```go
// MessageStatus is the response from GET /api/v1/mesh/{id}.
type MessageStatus struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

// CheckMessage queries the mesh-api for the current status of a message.
// Returns nil MessageStatus and nil error if the endpoint is unreachable or
// returns 404 (backward compat: old gateway has no such endpoint).
func (r *Reporter) CheckMessage(ctx context.Context, id string) (*MessageStatus, error) {
	if id == "" {
		return nil, nil
	}

	url := fmt.Sprintf("%s/api/v1/mesh/%s", r.gatewayURL, id)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create check request: %w", err)
	}
	setEnvelopeHeader(req, id)

	resp, err := r.httpClient.Do(req)
	if err != nil {
		// Network error — treat as "unknown, proceed with processing"
		slog.Warn("Pre-flight check failed (network), proceeding", "id", id, "error", err)
		return nil, nil
	}
	defer func() { _ = resp.Body.Close() }()

	// 404 = old gateway without this endpoint, proceed
	if resp.StatusCode == http.StatusNotFound {
		slog.Debug("Pre-flight check: endpoint not found (legacy gateway), proceeding", "id", id)
		return nil, nil
	}

	if resp.StatusCode >= 300 {
		slog.Warn("Pre-flight check returned unexpected status", "id", id, "status", resp.StatusCode)
		return nil, nil
	}

	var status MessageStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		slog.Warn("Pre-flight check: failed to decode response", "id", id, "error", err)
		return nil, nil
	}

	return &status, nil
}
```

**Design:** all error paths return `nil, nil` (proceed with processing). The
pre-flight check is an optimization to avoid wasted work, not a hard gate. If the
mesh-api is down, the sidecar must still process messages.

### 3.2 Pre-flight check in ProcessMessage

**File:** `src/asya-sidecar/internal/router/router.go`

Insert after envelope parsing and before the SLA pre-check (after line ~783
where `msg.Headers` is ensured). The check runs only when mesh status is enabled
(gateway URL available).

```go
// Pre-flight check: skip processing if message is already canceled or paused
if r.isMeshStatusEnabled(msg) {
	reporter := r.getReporter(msg)
	if reporter != nil {
		preflightCtx, preflightCancel := context.WithTimeout(ctx, 2*time.Second)
		msgStatus, _ := reporter.CheckMessage(preflightCtx, msg.ID)
		preflightCancel()

		if msgStatus != nil {
			switch msgStatus.Status {
			case "canceled":
				slog.Info("Pre-flight: message canceled, routing to x-sink",
					"id", msg.ID, "status", msgStatus.Status)

				if r.metrics != nil {
					r.metrics.RecordMessageProcessed(r.actorName, "preflight_canceled")
					r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
				}

				now := time.Now().UTC().Format(time.RFC3339)
				msg.Status = &envelopes.Status{
					Phase:     envelopes.PhaseCanceled,
					Reason:    "PreFlightCanceled",
					Actor:     r.actorName,
					CreatedAt: now,
					UpdatedAt: now,
				}
				return r.sendToSinkQueue(ctx, *msg)

			case "paused":
				slog.Info("Pre-flight: message paused, routing to x-sink",
					"id", msg.ID, "status", msgStatus.Status)

				if r.metrics != nil {
					r.metrics.RecordMessageProcessed(r.actorName, "preflight_paused")
					r.metrics.RecordProcessingDuration(r.actorName, time.Since(startTime))
				}

				now := time.Now().UTC().Format(time.RFC3339)
				msg.Status = &envelopes.Status{
					Phase:     envelopes.PhasePaused,
					Reason:    "PreFlightPaused",
					Actor:     r.actorName,
					CreatedAt: now,
					UpdatedAt: now,
				}
				return r.sendToSinkQueue(ctx, *msg)
			}
		}
	}
}
```

**Placement in ProcessMessage flow:**

```
parseAndValidateMessage
  -> ensure headers
  -> startProcessSpan
  -> PRE-FLIGHT CHECK (new)      <-- here
  -> SLA pre-check
  -> isEndActor?
  -> report "received" progress
  -> route validation
  -> report "processing" progress
  -> ensureAndUpdateStatus
  -> CallRuntime
  -> ...
```

The pre-flight check goes before SLA checks because a canceled message should be
discarded even if its SLA is fine. It goes after span creation so the discard is
traced.

### 3.3 New reason constants in envelope.go

**File:** `src/asya-sidecar/pkg/envelopes/envelope.go`

```go
const (
	ReasonCompleted        = "Completed"
	ReasonRuntimeError     = "RuntimeError"
	ReasonTimeout          = "Timeout"
	ReasonParseError       = "ParseError"
	ReasonRouteMismatch    = "RouteMismatch"
	ReasonPolicyExhausted  = "PolicyExhausted"
	ReasonPolicyRouted     = "PolicyRouted"
	ReasonPreFlightCanceled = "PreFlightCanceled"
	ReasonPreFlightPaused   = "PreFlightPaused"
)
```

---

## Backward Compatibility

### Scenario Matrix

| Sidecar version | Gateway version | Envelope header | Behavior |
|---|---|---|---|
| New | New mesh-api | `x-asya-gateway-url` present | Uses header URL, unified `/events` endpoint |
| New | Old gateway | No header, `ASYA_GATEWAY_URL` set | Uses env var, unified `/events` -> 404 -> falls back to legacy `/progress`, `/fly`, `/final` |
| New | Old gateway | No header, no env var | No reporting (same as today) |
| New | New mesh-api | Header present, `/events` returns 404 (edge) | Falls back to legacy endpoints |
| Old | New mesh-api | Header ignored | Uses env var (if set), old endpoints; mesh-api must handle old endpoints until old sidecars are retired |
| New | No gateway at all | No header, no env var | `isMeshStatusEnabled` returns false, all reporting skipped |

### Pre-flight check fallback

| Sidecar | Gateway | `GET /api/v1/mesh/{id}` result | Behavior |
|---|---|---|---|
| New | New mesh-api | 200 + status | Check status, skip if canceled/paused |
| New | Old gateway | 404 | `CheckMessage` returns nil, proceed normally |
| New | No gateway | Connection refused | `CheckMessage` returns nil, proceed normally |
| New | New mesh-api | 500 | `CheckMessage` returns nil, proceed normally |

---

## Tests

### Test 1: reporter_test.go — PostEvent unified endpoint

```go
func TestPostEvent_StatusEvent(t *testing.T) {
	var receivedEvent progress.MeshEvent
	var receivedPath string
	var receivedEnvelopeID string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedEnvelopeID = r.Header.Get("X-Asya-Envelope-ID")
		if err := json.NewDecoder(r.Body).Decode(&receivedEvent); err != nil {
			t.Errorf("Failed to decode: %v", err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := progress.NewReporter(server.URL, "test-actor")
	data, _ := json.Marshal(map[string]interface{}{"actor": "train", "progress": 50})

	err := reporter.PostEvent(context.Background(), "abc123", progress.MeshEvent{
		Type:   progress.EventTypeStatus,
		Status: "running",
		Data:   data,
	})

	assert(t, err == nil, "PostEvent returned error: %v", err)
	assert(t, receivedPath == "/api/v1/mesh/abc123/events", "path = %s", receivedPath)
	assert(t, receivedEnvelopeID == "abc123", "X-Asya-Envelope-ID = %s", receivedEnvelopeID)
	assert(t, receivedEvent.Type == progress.EventTypeStatus, "type = %s", receivedEvent.Type)
	assert(t, receivedEvent.Status == "running", "status = %s", receivedEvent.Status)
}
```

### Test 2: reporter_test.go — PostEvent FLY event

```go
func TestPostEvent_FlyEvent(t *testing.T) {
	var receivedEvent progress.MeshEvent

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&receivedEvent)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	reporter := progress.NewReporter(server.URL, "test-actor")
	flyData := json.RawMessage(`{"text":"hello world"}`)

	err := reporter.PostEvent(context.Background(), "abc123", progress.MeshEvent{
		Type: progress.EventTypeFly,
		Data: flyData,
	})

	assert(t, err == nil, "PostEvent returned error: %v", err)
	assert(t, receivedEvent.Type == progress.EventTypeFly, "type = %s", receivedEvent.Type)
}
```

### Test 3: reporter_test.go — PostEvent 404 fallback to legacy

```go
func TestPostEvent_FallbackToLegacy_On404(t *testing.T) {
	var legacyPath string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/events") {
			// New endpoint not recognized
			w.WriteHeader(http.StatusNotFound)
			return
		}
		// Legacy endpoint
		legacyPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	reporter := progress.NewReporter(server.URL, "test-actor")

	// FLY event should fall back to /mesh/{id}/fly
	err := reporter.PostEvent(context.Background(), "abc123", progress.MeshEvent{
		Type: progress.EventTypeFly,
		Data: json.RawMessage(`{"text":"token"}`),
	})

	assert(t, err == nil, "PostEvent returned error: %v", err)
	assert(t, legacyPath == "/mesh/abc123/fly", "legacy path = %s", legacyPath)
}
```

### Test 4: reporter_test.go — CheckMessage

```go
func TestCheckMessage_Canceled(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert(t, r.URL.Path == "/api/v1/mesh/abc123", "path = %s", r.URL.Path)
		assert(t, r.Method == http.MethodGet, "method = %s", r.Method)
		assert(t, r.Header.Get("X-Asya-Envelope-ID") == "abc123", "missing envelope ID header")

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(progress.MessageStatus{ID: "abc123", Status: "canceled"})
	}))
	defer server.Close()

	reporter := progress.NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	assert(t, err == nil, "CheckMessage returned error: %v", err)
	assert(t, status != nil, "status is nil")
	assert(t, status.Status == "canceled", "status = %s", status.Status)
}

func TestCheckMessage_404_ReturnsNil(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	reporter := progress.NewReporter(server.URL, "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	assert(t, err == nil, "CheckMessage returned error: %v", err)
	assert(t, status == nil, "status should be nil for 404")
}

func TestCheckMessage_NetworkError_ReturnsNil(t *testing.T) {
	reporter := progress.NewReporter("http://does-not-exist:99999", "test-actor")
	status, err := reporter.CheckMessage(context.Background(), "abc123")

	assert(t, err == nil, "CheckMessage returned error: %v", err)
	assert(t, status == nil, "status should be nil for network error")
}
```

### Test 5: router_test.go — Envelope header overrides env var

```go
func TestRouter_EnvelopeGatewayURLOverridesEnvVar(t *testing.T) {
	// Two mock servers: one for the env-var gateway, one for the envelope-header gateway
	envVarHit := false
	envVarServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		envVarHit = true
		w.WriteHeader(http.StatusOK)
	}))
	defer envVarServer.Close()

	headerHit := false
	headerServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		headerHit = true
		w.WriteHeader(http.StatusNoContent)
	}))
	defer headerServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		var env envelopes.Envelope
		json.Unmarshal(body, &env)
		return []runtime.RuntimeResponse{{
			Payload: json.RawMessage(`{"ok": true}`),
			Route:   env.Route.IncrementCurrent(),
		}}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    envVarServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})
	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := envelopes.Envelope{
		ID: "test-header-override",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Headers: map[string]interface{}{
			envelopes.HeaderGatewayURL: headerServer.URL,
		},
		Payload: json.RawMessage(`{"x": 1}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if envVarHit {
		t.Error("Env-var gateway should NOT have been hit when envelope header is present")
	}
	if !headerHit {
		t.Error("Envelope-header gateway should have been hit")
	}
}
```

### Test 6: router_test.go — Pre-flight canceled skips processing

```go
func TestRouter_PreFlightCheck_Canceled(t *testing.T) {
	runtimeCalled := false

	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/v1/mesh/") {
			// Pre-flight check: return canceled
			w.WriteHeader(http.StatusOK)
			json.NewEncoder(w).Encode(progress.MessageStatus{
				ID:     "test-canceled-123",
				Status: "canceled",
			})
			return
		}
		// Accept any POST (progress/events)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer gatewayServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		return []runtime.RuntimeResponse{{
			Payload: json.RawMessage(`{"ok": true}`),
		}}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    gatewayServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})
	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := envelopes.Envelope{
		ID: "test-canceled-123",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"x": 1}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if runtimeCalled {
		t.Error("Runtime should NOT have been called for canceled message")
	}

	// Verify message was routed to x-sink
	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message to x-sink, got %d", len(mockTransport.sentMessages))
	}

	if mockTransport.sentMessages[0].queue != "asya-default-x-sink" {
		t.Errorf("Message sent to %s, expected asya-default-x-sink",
			mockTransport.sentMessages[0].queue)
	}

	// Verify status on the routed message
	var sentMsg envelopes.Envelope
	json.Unmarshal(mockTransport.sentMessages[0].body, &sentMsg)

	if sentMsg.Status == nil || sentMsg.Status.Phase != envelopes.PhaseCanceled {
		t.Errorf("Expected phase=canceled, got %v", sentMsg.Status)
	}
}
```

### Test 7: router_test.go — Pre-flight 404 proceeds normally (backward compat)

```go
func TestRouter_PreFlightCheck_404_ProceedsNormally(t *testing.T) {
	runtimeCalled := false

	gatewayServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			// Old gateway: no GET /api/v1/mesh/{id} endpoint
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer gatewayServer.Close()

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		var env envelopes.Envelope
		json.Unmarshal(body, &env)
		return []runtime.RuntimeResponse{{
			Payload: json.RawMessage(`{"ok": true}`),
			Route:   env.Route.IncrementCurrent(),
		}}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    gatewayServer.URL,
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})
	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := envelopes.Envelope{
		ID: "test-legacy-123",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"x": 1}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if !runtimeCalled {
		t.Error("Runtime should have been called (pre-flight 404 means proceed)")
	}

	// Message should be routed to next-actor
	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message routed, got %d", len(mockTransport.sentMessages))
	}
	if mockTransport.sentMessages[0].queue != "asya-default-next-actor" {
		t.Errorf("Message sent to %s, expected asya-default-next-actor",
			mockTransport.sentMessages[0].queue)
	}
}
```

### Test 8: router_test.go — Pre-flight network error proceeds normally

```go
func TestRouter_PreFlightCheck_NetworkError_ProceedsNormally(t *testing.T) {
	runtimeCalled := false

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		var env envelopes.Envelope
		json.Unmarshal(body, &env)
		return []runtime.RuntimeResponse{{
			Payload: json.RawMessage(`{"ok": true}`),
			Route:   env.Route.IncrementCurrent(),
		}}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		// Gateway URL points to unreachable host
		GatewayURL: "http://192.0.2.1:1",
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})
	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := envelopes.Envelope{
		ID: "test-netfail-123",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		Payload: json.RawMessage(`{"x": 1}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if !runtimeCalled {
		t.Error("Runtime should have been called (pre-flight network error means proceed)")
	}
}
```

### Test 9: router_test.go — No gateway URL at all (no env var, no header)

```go
func TestRouter_NoGatewayURL_SkipsAllReporting(t *testing.T) {
	runtimeCalled := false

	socketPath := startMockRuntime(t, func(body []byte) ([]runtime.RuntimeResponse, int) {
		runtimeCalled = true
		var env envelopes.Envelope
		json.Unmarshal(body, &env)
		return []runtime.RuntimeResponse{{
			Payload: json.RawMessage(`{"ok": true}`),
			Route:   env.Route.IncrementCurrent(),
		}}, http.StatusOK
	})

	cfg := &config.Config{
		ActorName:     "test-actor",
		Namespace:     "default",
		SinkQueue:     "x-sink",
		SumpQueue:     "x-sump",
		Timeout:       2 * time.Second,
		TransportType: "rabbitmq",
		GatewayURL:    "", // no gateway
	}

	mockTransport := &mockTransport{}
	runtimeClient := runtime.NewClient(socketPath, 2*time.Second)
	m := metrics.NewMetrics("test", []config.CustomMetricConfig{})
	router := NewRouter(cfg, mockTransport, runtimeClient, m)

	inputMsg := envelopes.Envelope{
		ID: "test-no-gw-123",
		Route: envelopes.Route{
			Prev: []string{},
			Curr: "test-actor",
			Next: []string{"next-actor"},
		},
		// No x-asya-gateway-url header
		Payload: json.RawMessage(`{"x": 1}`),
	}
	msgBody, _ := json.Marshal(inputMsg)

	ctx := context.Background()
	err := router.ProcessMessage(ctx, transport.QueueMessage{ID: "msg-1", Body: msgBody})
	if err != nil {
		t.Fatalf("ProcessMessage failed: %v", err)
	}

	if !runtimeCalled {
		t.Error("Runtime should have been called even without gateway")
	}

	// Message routed normally
	if len(mockTransport.sentMessages) != 1 {
		t.Fatalf("Expected 1 message, got %d", len(mockTransport.sentMessages))
	}
	if mockTransport.sentMessages[0].queue != "asya-default-next-actor" {
		t.Errorf("Routed to %s, expected asya-default-next-actor",
			mockTransport.sentMessages[0].queue)
	}
}
```

---

## Implementation Order

1. **Add constants** to `envelope.go` (`HeaderGatewayURL`, `ReasonPreFlightCanceled`, `ReasonPreFlightPaused`)
2. **Add `PostEvent`, `CheckMessage`, `setEnvelopeHeader`** to `reporter.go`; update `ReportFinalError` to delegate to `PostEvent`
3. **Add `resolveGatewayURL`, `getReporter`** to `router.go`
4. **Update `isMeshStatusEnabled`** to check `resolveGatewayURL` instead of `r.progressReporter == nil`
5. **Update all `r.progressReporter.*` call sites** to use `r.getReporter(msg).*`
6. **Update `reportFinalStatusWithMessage`** to use `PostEvent` and `resolveGatewayURL`
7. **Add pre-flight check** block in `ProcessMessage`
8. **Write tests** for reporter (PostEvent, CheckMessage, fallback)
9. **Write tests** for router (envelope header, pre-flight canceled/paused/404/network-error)
10. **Run `make test-unit`** to verify, then `make lint`

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Pre-flight adds latency to every message | Low | 2s timeout; on failure/404, proceed immediately; GET is lightweight |
| Short-lived Reporter objects per envelope with unique URL | Low | Only created when envelope URL differs from env var; http.Client is reusable |
| Legacy fallback hides errors (silent 404 -> retry on old endpoint) | Low | Logged at Debug level; temporary until old gateways are retired |
| `isMeshStatusEnabled` change may enable reporting for envelopes that previously had none | Low | Only activates when `x-asya-gateway-url` header is explicitly set by a dispatcher |
