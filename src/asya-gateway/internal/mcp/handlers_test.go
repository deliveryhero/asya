package mcp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/config"
	"github.com/deliveryhero/asya/asya-gateway/internal/jobs"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandleEnvelopeProgress(t *testing.T) {
	tests := []struct {
		name           string
		method         string
		envelopeID     string
		jobExists      bool
		progressUpdate types.ProgressUpdate
		wantStatus     int
		wantProgress   float64
	}{
		{
			name:       "valid progress update - received",
			method:     http.MethodPost,
			envelopeID: "test-envelope-1",
			jobExists:  true,
			progressUpdate: types.ProgressUpdate{
				Actors:          []string{"parser", "processor", "finalizer"},
				CurrentActorIdx: 0,
				Status:          "received",
				Message:         "Envelope received",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 3.33,
		},
		{
			name:       "valid progress update - processing",
			method:     http.MethodPost,
			envelopeID: "test-envelope-2",
			jobExists:  true,
			progressUpdate: types.ProgressUpdate{
				Actors:          []string{"parser", "processor", "finalizer"},
				CurrentActorIdx: 1,
				Status:          "processing",
				Message:         "Processing data",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 50.0,
		},
		{
			name:       "valid progress update - completed",
			method:     http.MethodPost,
			envelopeID: "test-envelope-3",
			jobExists:  true,
			progressUpdate: types.ProgressUpdate{
				Actors:          []string{"parser", "processor", "finalizer"},
				CurrentActorIdx: 2,
				Status:          "completed",
				Message:         "Processing complete",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 100.0,
		},
		{
			name:       "invalid method",
			method:     http.MethodGet,
			envelopeID: "test-envelope-4",
			jobExists:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing envelope ID",
			method:     http.MethodPost,
			envelopeID: "",
			jobExists:  false,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create in-memory job store
			store := jobs.NewStore()

			// Create test envelope if needed
			if tt.jobExists {
				job := &types.Envelope{
					ID: tt.envelopeID,
					Route: types.Route{
						Actors:  []string{"parser", "processor", "finalizer"},
						Current: 0,
					},
					Status: types.EnvelopeStatusPending,
				}
				if err := store.Create(job); err != nil {
					t.Fatalf("Failed to create test envelope: %v", err)
				}
			}

			// Create handler
			handler := NewHandler(store)

			// Create request
			var req *http.Request
			if tt.method == http.MethodPost && tt.envelopeID != "" {
				body, _ := json.Marshal(tt.progressUpdate)
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/progress", bytes.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
			} else {
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/progress", nil)
			}

			// Create response recorder
			rr := httptest.NewRecorder()

			// Call handler
			handler.HandleEnvelopeProgress(rr, req)

			// Check status code
			if rr.Code != tt.wantStatus {
				t.Errorf("HandleEnvelopeProgress() status = %v, want %v", rr.Code, tt.wantStatus)
			}

			// Check response for successful cases
			if tt.wantStatus == http.StatusOK {
				var response map[string]interface{}
				if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
					t.Fatalf("Failed to decode response: %v", err)
				}

				if response["status"] != "ok" {
					t.Errorf("Response status = %v, want 'ok'", response["status"])
				}

				progressPercent := response["progress_percent"].(float64)
				if progressPercent < tt.wantProgress-0.5 || progressPercent > tt.wantProgress+0.5 {
					t.Errorf("Progress percent = %v, want ~%v", progressPercent, tt.wantProgress)
				}

				// Verify envelope was updated in store
				envelope, err := store.Get(tt.envelopeID)
				if err != nil {
					t.Fatalf("Failed to get updated envelope: %v", err)
				}

				if envelope.ProgressPercent < tt.wantProgress-0.5 || envelope.ProgressPercent > tt.wantProgress+0.5 {
					t.Errorf("Stored progress = %v, want ~%v", envelope.ProgressPercent, tt.wantProgress)
				}

				// Verify current actor matches the one at CurrentActorIdx
				if len(tt.progressUpdate.Actors) > 0 && tt.progressUpdate.CurrentActorIdx < len(tt.progressUpdate.Actors) {
					expectedActor := tt.progressUpdate.Actors[tt.progressUpdate.CurrentActorIdx]
					if envelope.CurrentActorName != expectedActor {
						t.Errorf("Current actor = %v, want %v", envelope.CurrentActorName, expectedActor)
					}
				}
			}
		})
	}
}

func TestHandleEnvelopeProgress_ProgressCalculation(t *testing.T) {
	tests := []struct {
		name         string
		actorIndex   int
		totalActors  int
		status       string
		wantProgress float64
	}{
		// 3-actor pipeline
		{"actor 0 received", 0, 3, "received", 3.33},
		{"actor 0 processing", 0, 3, "processing", 16.67},
		{"actor 0 completed", 0, 3, "completed", 33.33},
		{"actor 1 received", 1, 3, "received", 36.67},
		{"actor 1 processing", 1, 3, "processing", 50.0},
		{"actor 1 completed", 1, 3, "completed", 66.67},
		{"actor 2 received", 2, 3, "received", 70.0},
		{"actor 2 processing", 2, 3, "processing", 83.33},
		{"actor 2 completed", 2, 3, "completed", 100.0},

		// 5-actor pipeline
		{"5-actor: actor 2 processing", 2, 5, "processing", 50.0},
		{"5-actor: actor 4 completed", 4, 5, "completed", 100.0},

		// Single-actor pipeline
		{"1-actor: actor 0 received", 0, 1, "received", 10.0},
		{"1-actor: actor 0 processing", 0, 1, "processing", 50.0},
		{"1-actor: actor 0 completed", 0, 1, "completed", 100.0},

		// Edge case: zero total actors (division by zero protection)
		{"zero actors: received", 0, 0, "received", 0.0},
		{"zero actors: processing", 0, 0, "processing", 0.0},
		{"zero actors: completed", 0, 0, "completed", 0.0},
	}

	for i, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			envelopeID := fmt.Sprintf("test-envelope-%d", i)
			job := &types.Envelope{
				ID: envelopeID,
				Route: types.Route{
					Actors:  make([]string, tt.totalActors),
					Current: 0,
				},
				Status: types.EnvelopeStatusPending,
			}
			if err := store.Create(job); err != nil {
				t.Fatalf("Failed to create test envelope: %v", err)
			}

			// Create actors array based on totalActors
			actors := make([]string, tt.totalActors)
			for i := range actors {
				actors[i] = fmt.Sprintf("actor%d", i)
			}

			progressUpdate := types.ProgressUpdate{
				Actors:          actors,
				CurrentActorIdx: tt.actorIndex,
				Status:          tt.status,
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleEnvelopeProgress(rr, req)

			if rr.Code != http.StatusOK {
				t.Fatalf("Expected status 200, got %v", rr.Code)
			}

			var response map[string]interface{}
			if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
				t.Fatalf("Failed to decode response: %v", err)
			}

			progressPercent := response["progress_percent"].(float64)
			tolerance := 0.5
			if progressPercent < tt.wantProgress-tolerance || progressPercent > tt.wantProgress+tolerance {
				t.Errorf("Progress percent = %.2f, want %.2f (±%.1f)", progressPercent, tt.wantProgress, tolerance)
			}
		})
	}
}

func TestHandleEnvelopeProgress_SSENotification(t *testing.T) {
	store := jobs.NewStore()
	handler := NewHandler(store)

	envelopeID := "test-envelope-sse"
	job := &types.Envelope{
		ID: envelopeID,
		Route: types.Route{
			Actors:  []string{"actor1", "actor2"},
			Current: 0,
		},
		Status: types.EnvelopeStatusPending,
	}
	if err := store.Create(job); err != nil {
		t.Fatalf("Failed to create test envelope: %v", err)
	}

	// Subscribe to envelope updates
	updateChan := store.Subscribe(envelopeID)
	defer store.Unsubscribe(envelopeID, updateChan)

	// Send progress update
	progressUpdate := types.ProgressUpdate{
		Actors:          []string{"actor1", "actor2"},
		CurrentActorIdx: 0,
		Status:          "processing",
		Message:         "Processing actor 1",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/envelopes/"+envelopeID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Expected status 200, got %v", rr.Code)
	}

	// Wait for SSE notification
	select {
	case update := <-updateChan:
		if update.ID != envelopeID {
			t.Errorf("Update envelope ID = %v, want %v", update.ID, envelopeID)
		}
		if update.CurrentActorIdx == nil || *update.CurrentActorIdx != 0 {
			t.Errorf("Update current actor idx = %v, want 0", update.CurrentActorIdx)
		}
		if len(update.Actors) < 1 || update.Actors[0] != "actor1" {
			t.Errorf("Update actors = %v, want [actor1, ...]", update.Actors)
		}
		if update.EnvelopeState == nil || *update.EnvelopeState != "processing" {
			t.Errorf("Update envelope state = %v, want processing", update.EnvelopeState)
		}
		if update.ProgressPercent == nil || *update.ProgressPercent < 24.5 || *update.ProgressPercent > 25.5 {
			t.Errorf("Update progress = %v, want ~25.0", update.ProgressPercent)
		}
	case <-time.After(1 * time.Second):
		t.Fatal("Did not receive SSE notification within timeout")
	}
}

// TestHandleToolCall tests the REST API endpoint for calling MCP tools
func TestHandleToolCall(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		body       interface{}
		setupMCP   bool
		toolName   string
		wantStatus int
		checkBody  bool
	}{
		{
			name:   "valid tool call - success",
			method: http.MethodPost,
			body: map[string]interface{}{
				"name":      "test_tool",
				"arguments": map[string]interface{}{"input": "test_value"},
			},
			setupMCP:   true,
			toolName:   "test_tool",
			wantStatus: http.StatusOK,
			checkBody:  true,
		},
		{
			name:       "invalid method - GET not allowed",
			method:     http.MethodGet,
			body:       nil,
			setupMCP:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - PUT not allowed",
			method:     http.MethodPut,
			body:       map[string]interface{}{"name": "test"},
			setupMCP:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid request body - malformed JSON",
			method:     http.MethodPost,
			body:       "not valid json",
			setupMCP:   true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing tool name",
			method:     http.MethodPost,
			body:       map[string]interface{}{"arguments": map[string]interface{}{"key": "value"}},
			setupMCP:   true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:   "empty tool name",
			method: http.MethodPost,
			body: map[string]interface{}{
				"name":      "",
				"arguments": map[string]interface{}{},
			},
			setupMCP:   true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:   "server not initialized",
			method: http.MethodPost,
			body: map[string]interface{}{
				"name":      "test_tool",
				"arguments": map[string]interface{}{},
			},
			setupMCP:   false,
			wantStatus: http.StatusInternalServerError,
		},
		{
			name:   "tool not found",
			method: http.MethodPost,
			body: map[string]interface{}{
				"name":      "nonexistent_tool",
				"arguments": map[string]interface{}{},
			},
			setupMCP:   true,
			toolName:   "test_tool",
			wantStatus: http.StatusNotFound,
		},
		{
			name:   "nil arguments",
			method: http.MethodPost,
			body: map[string]interface{}{
				"name":      "test_tool",
				"arguments": nil,
			},
			setupMCP:   true,
			toolName:   "test_tool",
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			if tt.setupMCP {
				cfg := &config.Config{
					Tools: []config.Tool{
						{
							Name:        "test_tool",
							Description: "Test tool",
							Route:       config.RouteSpec{Actors: []string{"actor1"}},
						},
					},
				}
				queueClient := &MockQueueClient{}
				mcpServer := NewServer(store, queueClient, cfg)
				handler.SetServer(mcpServer)
			}

			var req *http.Request
			if tt.body == nil {
				req = httptest.NewRequest(tt.method, "/tools/call", nil)
			} else if bodyStr, ok := tt.body.(string); ok {
				req = httptest.NewRequest(tt.method, "/tools/call", bytes.NewReader([]byte(bodyStr)))
			} else {
				body, _ := json.Marshal(tt.body)
				req = httptest.NewRequest(tt.method, "/tools/call", bytes.NewReader(body))
			}
			req.Header.Set("Content-Type", "application/json")

			rr := httptest.NewRecorder()
			handler.HandleToolCall(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleToolCall() status = %v, want %v, body = %s", rr.Code, tt.wantStatus, rr.Body.String())
			}

			if tt.checkBody && tt.wantStatus == http.StatusOK {
				var result map[string]interface{}
				if err := json.NewDecoder(rr.Body).Decode(&result); err != nil {
					t.Errorf("Failed to decode response: %v", err)
				}
			}
		})
	}
}

// TestHandleEnvelopeStatus tests the GET /envelopes/{id} endpoint
func TestHandleEnvelopeStatus(t *testing.T) {
	tests := []struct {
		name        string
		method      string
		envelopeID  string
		setupEnv    bool
		envStatus   types.EnvelopeStatus
		wantStatus  int
		checkFields bool
	}{
		{
			name:        "valid GET - pending envelope",
			method:      http.MethodGet,
			envelopeID:  "test-env-1",
			setupEnv:    true,
			envStatus:   types.EnvelopeStatusPending,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:        "valid GET - running envelope",
			method:      http.MethodGet,
			envelopeID:  "test-env-2",
			setupEnv:    true,
			envStatus:   types.EnvelopeStatusRunning,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:        "valid GET - succeeded envelope",
			method:      http.MethodGet,
			envelopeID:  "test-env-3",
			setupEnv:    true,
			envStatus:   types.EnvelopeStatusSucceeded,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:       "invalid method - POST not allowed",
			method:     http.MethodPost,
			envelopeID: "test-env-4",
			setupEnv:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - PUT not allowed",
			method:     http.MethodPut,
			envelopeID: "test-env-5",
			setupEnv:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - DELETE not allowed",
			method:     http.MethodDelete,
			envelopeID: "test-env-6",
			setupEnv:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing envelope ID",
			method:     http.MethodGet,
			envelopeID: "",
			setupEnv:   false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "envelope not found",
			method:     http.MethodGet,
			envelopeID: "nonexistent-envelope",
			setupEnv:   false,
			wantStatus: http.StatusNotFound,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			if tt.setupEnv {
				env := &types.Envelope{
					ID: tt.envelopeID,
					Route: types.Route{
						Actors:  []string{"actor1", "actor2"},
						Current: 0,
					},
					TotalActors: 2,
				}
				if err := store.Create(env); err != nil {
					t.Fatalf("Failed to create test envelope: %v", err)
				}

				if tt.envStatus != types.EnvelopeStatusPending {
					update := types.EnvelopeUpdate{
						ID:        tt.envelopeID,
						Status:    tt.envStatus,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update envelope status: %v", err)
					}
				}
			}

			req := httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID, nil)
			rr := httptest.NewRecorder()

			handler.HandleEnvelopeStatus(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleEnvelopeStatus() status = %v, want %v", rr.Code, tt.wantStatus)
			}

			if tt.checkFields && tt.wantStatus == http.StatusOK {
				var envelope types.Envelope
				if err := json.NewDecoder(rr.Body).Decode(&envelope); err != nil {
					t.Fatalf("Failed to decode response: %v", err)
				}

				if envelope.ID != tt.envelopeID {
					t.Errorf("Envelope ID = %v, want %v", envelope.ID, tt.envelopeID)
				}
				if envelope.Status != tt.envStatus {
					t.Errorf("Envelope status = %v, want %v", envelope.Status, tt.envStatus)
				}
			}
		})
	}
}

// TestHandleEnvelopeActive tests the GET /envelopes/{id}/active endpoint
func TestHandleEnvelopeActive(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		envelopeID string
		setupEnv   bool
		envStatus  types.EnvelopeStatus
		wantStatus int
		wantActive bool
	}{
		{
			name:       "active envelope - pending",
			method:     http.MethodGet,
			envelopeID: "test-active-1",
			setupEnv:   true,
			envStatus:  types.EnvelopeStatusPending,
			wantStatus: http.StatusOK,
			wantActive: true,
		},
		{
			name:       "active envelope - running",
			method:     http.MethodGet,
			envelopeID: "test-active-2",
			setupEnv:   true,
			envStatus:  types.EnvelopeStatusRunning,
			wantStatus: http.StatusOK,
			wantActive: true,
		},
		{
			name:       "inactive envelope - succeeded",
			method:     http.MethodGet,
			envelopeID: "test-active-3",
			setupEnv:   true,
			envStatus:  types.EnvelopeStatusSucceeded,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
		{
			name:       "inactive envelope - failed",
			method:     http.MethodGet,
			envelopeID: "test-active-4",
			setupEnv:   true,
			envStatus:  types.EnvelopeStatusFailed,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
		{
			name:       "invalid method - POST not allowed",
			method:     http.MethodPost,
			envelopeID: "test-active-5",
			setupEnv:   true,
			envStatus:  types.EnvelopeStatusPending,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "empty envelope ID path",
			method:     http.MethodGet,
			envelopeID: "",
			setupEnv:   false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "envelope not found - inactive",
			method:     http.MethodGet,
			envelopeID: "nonexistent",
			setupEnv:   false,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			if tt.setupEnv {
				env := &types.Envelope{
					ID: tt.envelopeID,
					Route: types.Route{
						Actors:  []string{"actor1"},
						Current: 0,
					},
				}
				if err := store.Create(env); err != nil {
					t.Fatalf("Failed to create test envelope: %v", err)
				}

				if tt.envStatus != types.EnvelopeStatusPending {
					update := types.EnvelopeUpdate{
						ID:        tt.envelopeID,
						Status:    tt.envStatus,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update envelope status: %v", err)
					}
				}
			}

			var req *http.Request
			if tt.envelopeID == "" {
				req = httptest.NewRequest(tt.method, "/envelopes//active", nil)
			} else {
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/active", nil)
			}
			rr := httptest.NewRecorder()

			handler.HandleEnvelopeActive(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleEnvelopeActive() status = %v, want %v", rr.Code, tt.wantStatus)
			}

			if tt.wantStatus == http.StatusOK || tt.wantStatus == http.StatusGone {
				var response map[string]bool
				if err := json.NewDecoder(rr.Body).Decode(&response); err != nil {
					t.Fatalf("Failed to decode response: %v", err)
				}

				if active, ok := response["active"]; !ok {
					t.Error("Response missing 'active' field")
				} else if active != tt.wantActive {
					t.Errorf("Active = %v, want %v", active, tt.wantActive)
				}
			}
		})
	}
}

// TestHandleEnvelopeFinal tests the POST /envelopes/{id}/final endpoint
func TestHandleEnvelopeFinal(t *testing.T) {
	tests := []struct {
		name        string
		method      string
		envelopeID  string
		setupEnv    bool
		finalUpdate interface{}
		wantStatus  int
		wantEnvStat types.EnvelopeStatus
		checkUpdate bool
	}{
		{
			name:       "valid success - basic",
			method:     http.MethodPost,
			envelopeID: "test-final-1",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-1",
				"status": "succeeded",
				"result": map[string]interface{}{"output": "success"},
			},
			wantStatus:  http.StatusOK,
			wantEnvStat: types.EnvelopeStatusSucceeded,
			checkUpdate: true,
		},
		{
			name:       "valid success - with S3 URI",
			method:     http.MethodPost,
			envelopeID: "test-final-2",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-2",
				"status": "succeeded",
				"result": map[string]interface{}{"data": "result"},
				"metadata": map[string]interface{}{
					"s3_uri": "s3://bucket/key",
				},
			},
			wantStatus:  http.StatusOK,
			wantEnvStat: types.EnvelopeStatusSucceeded,
			checkUpdate: true,
		},
		{
			name:       "valid failure - with error message",
			method:     http.MethodPost,
			envelopeID: "test-final-3",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-3",
				"status": "failed",
				"error":  "Processing error occurred",
			},
			wantStatus:  http.StatusOK,
			wantEnvStat: types.EnvelopeStatusFailed,
			checkUpdate: true,
		},
		{
			name:       "valid failure - without error message",
			method:     http.MethodPost,
			envelopeID: "test-final-4",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-4",
				"status": "failed",
			},
			wantStatus:  http.StatusOK,
			wantEnvStat: types.EnvelopeStatusFailed,
			checkUpdate: true,
		},
		{
			name:       "invalid method - GET not allowed",
			method:     http.MethodGet,
			envelopeID: "test-final-5",
			setupEnv:   true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - PUT not allowed",
			method:     http.MethodPut,
			envelopeID: "test-final-6",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"status": "succeeded",
			},
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing envelope ID",
			method:     http.MethodPost,
			envelopeID: "",
			setupEnv:   false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:        "invalid JSON body",
			method:      http.MethodPost,
			envelopeID:  "test-final-7",
			setupEnv:    true,
			finalUpdate: "not valid json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:       "invalid status - unknown value",
			method:     http.MethodPost,
			envelopeID: "test-final-8",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"job_id": "test-final-8",
				"status": "unknown_status",
			},
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid status - empty string",
			method:     http.MethodPost,
			envelopeID: "test-final-9",
			setupEnv:   true,
			finalUpdate: map[string]interface{}{
				"job_id": "test-final-9",
				"status": "",
			},
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "envelope not found",
			method:     http.MethodPost,
			envelopeID: "nonexistent",
			setupEnv:   false,
			finalUpdate: map[string]interface{}{
				"job_id": "nonexistent",
				"status": "succeeded",
			},
			wantStatus: http.StatusInternalServerError,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			if tt.setupEnv {
				env := &types.Envelope{
					ID: tt.envelopeID,
					Route: types.Route{
						Actors:  []string{"actor1"},
						Current: 0,
					},
					Status: types.EnvelopeStatusRunning,
				}
				if err := store.Create(env); err != nil {
					t.Fatalf("Failed to create test envelope: %v", err)
				}
			}

			var req *http.Request
			if tt.finalUpdate == nil {
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/final", nil)
			} else if bodyStr, ok := tt.finalUpdate.(string); ok {
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/final", bytes.NewReader([]byte(bodyStr)))
			} else {
				body, _ := json.Marshal(tt.finalUpdate)
				req = httptest.NewRequest(tt.method, "/envelopes/"+tt.envelopeID+"/final", bytes.NewReader(body))
			}
			req.Header.Set("Content-Type", "application/json")

			rr := httptest.NewRecorder()
			handler.HandleEnvelopeFinal(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleEnvelopeFinal() status = %v, want %v, body = %s", rr.Code, tt.wantStatus, rr.Body.String())
			}

			if tt.checkUpdate && tt.wantStatus == http.StatusOK {
				envelope, err := store.Get(tt.envelopeID)
				if err != nil {
					t.Fatalf("Failed to get updated envelope: %v", err)
				}

				if envelope.Status != tt.wantEnvStat {
					t.Errorf("Envelope status = %v, want %v", envelope.Status, tt.wantEnvStat)
				}

				if tt.wantEnvStat == types.EnvelopeStatusSucceeded && envelope.Result == nil {
					updateMap := tt.finalUpdate.(map[string]interface{})
					if _, hasResult := updateMap["result"]; hasResult {
						t.Error("Expected result to be set for succeeded envelope")
					}
				}

				if tt.wantEnvStat == types.EnvelopeStatusFailed {
					updateMap := tt.finalUpdate.(map[string]interface{})
					if errMsg, hasError := updateMap["error"].(string); hasError && errMsg != "" {
						if envelope.Error == "" {
							t.Error("Expected error message to be set")
						}
					}
				}
			}
		})
	}
}

func TestEnvelopePathRegex(t *testing.T) {
	tests := []struct {
		name        string
		path        string
		regex       string
		wantMatch   bool
		wantID      string
		description string
	}{
		{
			name:        "valid envelope status path",
			path:        "/envelopes/abc-123",
			regex:       "status",
			wantMatch:   true,
			wantID:      "abc-123",
			description: "Should match /envelopes/{id}",
		},
		{
			name:        "valid envelope stream path",
			path:        "/envelopes/test-id-456/stream",
			regex:       "stream",
			wantMatch:   true,
			wantID:      "test-id-456",
			description: "Should match /envelopes/{id}/stream",
		},
		{
			name:        "valid envelope active path",
			path:        "/envelopes/uuid-789/active",
			regex:       "active",
			wantMatch:   true,
			wantID:      "uuid-789",
			description: "Should match /envelopes/{id}/active",
		},
		{
			name:        "valid envelope progress path",
			path:        "/envelopes/env-001/progress",
			regex:       "progress",
			wantMatch:   true,
			wantID:      "env-001",
			description: "Should match /envelopes/{id}/progress",
		},
		{
			name:        "valid envelope final path",
			path:        "/envelopes/final-test/final",
			regex:       "final",
			wantMatch:   true,
			wantID:      "final-test",
			description: "Should match /envelopes/{id}/final",
		},
		{
			name:        "UUID format envelope ID",
			path:        "/envelopes/550e8400-e29b-41d4-a716-446655440000",
			regex:       "status",
			wantMatch:   true,
			wantID:      "550e8400-e29b-41d4-a716-446655440000",
			description: "Should match UUID format IDs",
		},
		{
			name:        "empty envelope ID",
			path:        "/envelopes//stream",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject empty envelope ID",
		},
		{
			name:        "missing envelope ID",
			path:        "/envelopes/",
			regex:       "status",
			wantMatch:   false,
			description: "Should reject missing envelope ID",
		},
		{
			name:        "wrong suffix",
			path:        "/envelopes/test-id/wrong",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject wrong suffix",
		},
		{
			name:        "extra path segments",
			path:        "/envelopes/test-id/stream/extra",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject extra path segments",
		},
		{
			name:        "envelope ID with slashes",
			path:        "/envelopes/id/with/slashes/stream",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject envelope ID containing slashes",
		},
		{
			name:        "status path with trailing slash",
			path:        "/envelopes/test-id/",
			regex:       "status",
			wantMatch:   false,
			description: "Should reject trailing slash",
		},
		{
			name:        "stream path without trailing slash",
			path:        "/envelopes/test-id/stream",
			regex:       "stream",
			wantMatch:   true,
			wantID:      "test-id",
			description: "Should match stream path without trailing slash",
		},
		{
			name:        "alphanumeric with hyphens and underscores",
			path:        "/envelopes/test_id-123_abc/progress",
			regex:       "progress",
			wantMatch:   true,
			wantID:      "test_id-123_abc",
			description: "Should match IDs with hyphens and underscores",
		},
		{
			name:        "numeric only ID",
			path:        "/envelopes/123456/final",
			regex:       "final",
			wantMatch:   true,
			wantID:      "123456",
			description: "Should match numeric only IDs",
		},
	}

	regexMap := map[string]*regexp.Regexp{
		"status":   envelopePathRegex,
		"stream":   envelopeStreamPathRegex,
		"active":   envelopeActivePathRegex,
		"progress": envelopeProgressPathRegex,
		"final":    envelopeFinalPathRegex,
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			pattern := regexMap[tt.regex]
			if pattern == nil {
				t.Fatalf("Unknown regex type: %s", tt.regex)
			}

			matches := pattern.FindStringSubmatch(tt.path)

			if tt.wantMatch {
				if matches == nil {
					t.Errorf("Expected path %q to match regex, but it didn't. %s", tt.path, tt.description)
					return
				}
				if len(matches) < 2 {
					t.Errorf("Expected regex to capture envelope ID, but got %d matches", len(matches))
					return
				}
				gotID := matches[1]
				if gotID != tt.wantID {
					t.Errorf("Expected envelope ID %q, got %q", tt.wantID, gotID)
				}
			} else {
				if matches != nil {
					t.Errorf("Expected path %q to NOT match regex, but it did. %s. Captured ID: %q", tt.path, tt.description, matches[1])
				}
			}
		})
	}
}

func TestEnvelopePathRegex_EdgeCases(t *testing.T) {
	store := jobs.NewStore()
	handler := NewHandler(store)

	tests := []struct {
		name        string
		path        string
		method      string
		handlerFunc func(http.ResponseWriter, *http.Request)
		wantStatus  int
		description string
	}{
		{
			name:        "double slashes in path",
			path:        "/envelopes//active",
			method:      http.MethodGet,
			handlerFunc: handler.HandleEnvelopeActive,
			wantStatus:  http.StatusBadRequest,
			description: "Regex should reject double slashes",
		},
		{
			name:        "malformed path missing prefix",
			path:        "/wrong/test-id/stream",
			method:      http.MethodGet,
			handlerFunc: handler.HandleEnvelopeStream,
			wantStatus:  http.StatusBadRequest,
			description: "Regex should reject wrong prefix",
		},
		{
			name:        "path with query parameters",
			path:        "/envelopes/test-id?foo=bar",
			method:      http.MethodGet,
			handlerFunc: handler.HandleEnvelopeStatus,
			wantStatus:  http.StatusNotFound,
			description: "Query parameters are stripped by URL.Path, envelope not found",
		},
		{
			name:        "extremely long envelope ID",
			path:        "/envelopes/" + strings.Repeat("a", 1000) + "/progress",
			method:      http.MethodPost,
			handlerFunc: handler.HandleEnvelopeProgress,
			wantStatus:  http.StatusBadRequest,
			description: "Should handle extremely long IDs gracefully",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.path, nil)
			rr := httptest.NewRecorder()

			tt.handlerFunc(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("%s: got status %d, want %d", tt.description, rr.Code, tt.wantStatus)
			}
		})
	}
}

func TestHandleEnvelopeCreate(t *testing.T) {
	tests := []struct {
		name         string
		method       string
		requestBody  map[string]interface{}
		wantStatus   int
		wantEnvelope bool
	}{
		{
			name:   "valid fanout envelope creation",
			method: http.MethodPost,
			requestBody: map[string]interface{}{
				"id":        "abc-123-1",
				"parent_id": "abc-123",
				"actors":    []string{"actor1", "actor2"},
				"current":   1,
			},
			wantStatus:   http.StatusCreated,
			wantEnvelope: true,
		},
		{
			name:   "missing id field",
			method: http.MethodPost,
			requestBody: map[string]interface{}{
				"parent_id": "abc-123",
				"actors":    []string{"actor1"},
				"current":   1,
			},
			wantStatus:   http.StatusBadRequest,
			wantEnvelope: false,
		},
		{
			name:         "invalid json",
			method:       http.MethodPost,
			requestBody:  nil,
			wantStatus:   http.StatusBadRequest,
			wantEnvelope: false,
		},
		{
			name:         "wrong method GET",
			method:       http.MethodGet,
			requestBody:  nil,
			wantStatus:   http.StatusMethodNotAllowed,
			wantEnvelope: false,
		},
		{
			name:         "wrong method PUT",
			method:       http.MethodPut,
			requestBody:  nil,
			wantStatus:   http.StatusMethodNotAllowed,
			wantEnvelope: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := jobs.NewStore()
			handler := NewHandler(store)

			var body []byte
			var err error
			if tt.requestBody != nil {
				body, err = json.Marshal(tt.requestBody)
				if err != nil {
					t.Fatalf("Failed to marshal request body: %v", err)
				}
			} else if tt.method == http.MethodPost {
				body = []byte("invalid json{")
			}

			req := httptest.NewRequest(tt.method, "/envelopes", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleEnvelopeCreate(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("got status %d, want %d", rr.Code, tt.wantStatus)
			}

			// Verify envelope was created if expected
			if tt.wantEnvelope {
				envelopeID := tt.requestBody["id"].(string)
				envelope, err := store.Get(envelopeID)
				if err != nil {
					t.Errorf("Envelope not found: %v", err)
				}
				if envelope == nil {
					t.Error("Envelope is nil")
				} else {
					if envelope.ID != envelopeID {
						t.Errorf("Envelope ID = %v, want %v", envelope.ID, envelopeID)
					}
					parentID := tt.requestBody["parent_id"].(string)
					if envelope.ParentID == nil || *envelope.ParentID != parentID {
						t.Errorf("Envelope ParentID = %v, want %v", envelope.ParentID, parentID)
					}
					if envelope.Status != types.EnvelopeStatusPending {
						t.Errorf("Envelope Status = %v, want Pending", envelope.Status)
					}
				}
			}
		})
	}
}

func TestHandleEnvelopeCreate_DuplicateID(t *testing.T) {
	store := jobs.NewStore()
	handler := NewHandler(store)

	// Create first envelope
	envelope := &types.Envelope{
		ID:     "abc-123-1",
		Status: types.EnvelopeStatusPending,
		Route:  types.Route{Actors: []string{"actor1"}, Current: 0},
	}
	if err := store.Create(envelope); err != nil {
		t.Fatalf("Failed to create envelope: %v", err)
	}

	// Try to create duplicate
	requestBody := map[string]interface{}{
		"id":        "abc-123-1",
		"parent_id": "abc-123",
		"actors":    []string{"actor1"},
		"current":   1,
	}

	body, _ := json.Marshal(requestBody)
	req := httptest.NewRequest(http.MethodPost, "/envelopes", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleEnvelopeCreate(rr, req)

	// Should return error
	if rr.Code == http.StatusCreated {
		t.Error("Should not allow duplicate envelope ID")
	}
}
