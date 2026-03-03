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
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

func TestHandleMeshProgress(t *testing.T) {
	tests := []struct {
		name           string
		method         string
		taskID         string
		jobExists      bool
		progressUpdate types.ProgressUpdate
		wantStatus     int
		wantProgress   float64
	}{
		{
			name:      "valid progress update - received",
			method:    http.MethodPost,
			taskID:    "test-task-1",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Prev:    []string{},
				Curr:    "parser",
				Next:    []string{"processor", "finalizer"},
				Status:  "received",
				Message: "Task received",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 3.33,
		},
		{
			name:      "valid progress update - processing",
			method:    http.MethodPost,
			taskID:    "test-task-2",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Prev:    []string{"parser"},
				Curr:    "processor",
				Next:    []string{"finalizer"},
				Status:  "processing",
				Message: "Processing data",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 50.0,
		},
		{
			name:      "valid progress update - completed",
			method:    http.MethodPost,
			taskID:    "test-task-3",
			jobExists: true,
			progressUpdate: types.ProgressUpdate{
				Prev:    []string{"parser", "processor"},
				Curr:    "finalizer",
				Next:    []string{},
				Status:  "completed",
				Message: "Processing complete",
			},
			wantStatus:   http.StatusOK,
			wantProgress: 100.0,
		},
		{
			name:       "invalid method",
			method:     http.MethodGet,
			taskID:     "test-task-4",
			jobExists:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing task ID",
			method:     http.MethodPost,
			taskID:     "",
			jobExists:  false,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create in-memory task store
			store := taskstore.NewStore()

			// Create test task if needed
			if tt.jobExists {
				task := &types.Task{
					ID: tt.taskID,
					Route: types.Route{
						Prev: []string{},
						Curr: "parser",
						Next: []string{"processor", "finalizer"},
					},
					Status: types.TaskStatusPending,
				}
				if err := store.Create(task); err != nil {
					t.Fatalf("Failed to create test task: %v", err)
				}
			}

			// Create handler
			handler := NewHandler(store)

			// Create request
			var req *http.Request
			if tt.method == http.MethodPost && tt.taskID != "" {
				body, _ := json.Marshal(tt.progressUpdate)
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/progress", bytes.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
			} else {
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/progress", nil)
			}

			// Create response recorder
			rr := httptest.NewRecorder()

			// Call handler
			handler.HandleMeshProgress(rr, req)

			// Check status code
			if rr.Code != tt.wantStatus {
				t.Errorf("HandleMeshProgress() status = %v, want %v", rr.Code, tt.wantStatus)
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

				// Verify task was updated in store
				task, err := store.Get(tt.taskID)
				if err != nil {
					t.Fatalf("Failed to get updated task: %v", err)
				}

				if task.ProgressPercent < tt.wantProgress-0.5 || task.ProgressPercent > tt.wantProgress+0.5 {
					t.Errorf("Stored progress = %v, want ~%v", task.ProgressPercent, tt.wantProgress)
				}

				// Verify current actor matches Curr field
				if tt.progressUpdate.Curr != "" {
					if task.CurrentActorName != tt.progressUpdate.Curr {
						t.Errorf("Current actor = %v, want %v", task.CurrentActorName, tt.progressUpdate.Curr)
					}
				}
			}
		})
	}
}

func TestHandleMeshProgress_ProgressCalculation(t *testing.T) {
	tests := []struct {
		name         string
		prev         []string
		curr         string
		next         []string
		status       string
		wantProgress float64
	}{
		// 3-actor pipeline
		{"actor 0 received", []string{}, "actor0", []string{"actor1", "actor2"}, "received", 3.33},
		{"actor 0 processing", []string{}, "actor0", []string{"actor1", "actor2"}, "processing", 16.67},
		{"actor 0 completed", []string{}, "actor0", []string{"actor1", "actor2"}, "completed", 33.33},
		{"actor 1 received", []string{"actor0"}, "actor1", []string{"actor2"}, "received", 36.67},
		{"actor 1 processing", []string{"actor0"}, "actor1", []string{"actor2"}, "processing", 50.0},
		{"actor 1 completed", []string{"actor0"}, "actor1", []string{"actor2"}, "completed", 66.67},
		{"actor 2 received", []string{"actor0", "actor1"}, "actor2", []string{}, "received", 70.0},
		{"actor 2 processing", []string{"actor0", "actor1"}, "actor2", []string{}, "processing", 83.33},
		{"actor 2 completed", []string{"actor0", "actor1"}, "actor2", []string{}, "completed", 100.0},

		// 5-actor pipeline
		{"5-actor: actor 2 processing", []string{"actor0", "actor1"}, "actor2", []string{"actor3", "actor4"}, "processing", 50.0},
		{"5-actor: actor 4 completed", []string{"actor0", "actor1", "actor2", "actor3"}, "actor4", []string{}, "completed", 100.0},

		// Single-actor pipeline
		{"1-actor: actor 0 received", []string{}, "actor0", []string{}, "received", 10.0},
		{"1-actor: actor 0 processing", []string{}, "actor0", []string{}, "processing", 50.0},
		{"1-actor: actor 0 completed", []string{}, "actor0", []string{}, "completed", 100.0},
	}

	for i, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := taskstore.NewStore()
			handler := NewHandler(store)

			taskID := fmt.Sprintf("test-task-%d", i)
			task := &types.Task{
				ID: taskID,
				Route: types.Route{
					Prev: []string{},
					Curr: "actor0",
					Next: []string{"actor1", "actor2"},
				},
				Status: types.TaskStatusPending,
			}
			if err := store.Create(task); err != nil {
				t.Fatalf("Failed to create test task: %v", err)
			}

			progressUpdate := types.ProgressUpdate{
				Prev:   tt.prev,
				Curr:   tt.curr,
				Next:   tt.next,
				Status: tt.status,
			}

			body, _ := json.Marshal(progressUpdate)
			req := httptest.NewRequest(http.MethodPost, "/mesh/"+taskID+"/progress", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleMeshProgress(rr, req)

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

func TestHandleMeshProgress_SSENotification(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	taskID := "test-task-sse"
	task := &types.Task{
		ID: taskID,
		Route: types.Route{
			Prev: []string{},
			Curr: "actor1",
			Next: []string{"actor2"},
		},
		Status: types.TaskStatusPending,
	}
	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create test task: %v", err)
	}

	// Subscribe to task updates
	updateChan := store.Subscribe(taskID)
	defer store.Unsubscribe(taskID, updateChan)

	// Send progress update
	progressUpdate := types.ProgressUpdate{
		Prev:    []string{},
		Curr:    "actor1",
		Next:    []string{"actor2"},
		Status:  "processing",
		Message: "Processing actor 1",
	}

	body, _ := json.Marshal(progressUpdate)
	req := httptest.NewRequest(http.MethodPost, "/mesh/"+taskID+"/progress", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleMeshProgress(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("Expected status 200, got %v", rr.Code)
	}

	// Wait for SSE notification
	select {
	case update := <-updateChan:
		if update.ID != taskID {
			t.Errorf("Update task ID = %v, want %v", update.ID, taskID)
		}
		if update.Curr != "actor1" {
			t.Errorf("Update curr = %v, want actor1", update.Curr)
		}
		if update.TaskState == nil || *update.TaskState != "processing" {
			t.Errorf("Update task state = %v, want processing", update.TaskState)
		}
		// 2-actor pipeline, actor 0 processing: (0+0.5)*100/2 = 25.0
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
			store := taskstore.NewStore()
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

// TestHandleMeshStatus tests the GET /mesh/{id} endpoint
func TestHandleMeshStatus(t *testing.T) {
	tests := []struct {
		name        string
		method      string
		taskID      string
		setupTask   bool
		taskStatus  types.TaskStatus
		wantStatus  int
		checkFields bool
	}{
		{
			name:        "valid GET - pending task",
			method:      http.MethodGet,
			taskID:      "test-task-1",
			setupTask:   true,
			taskStatus:  types.TaskStatusPending,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:        "valid GET - running task",
			method:      http.MethodGet,
			taskID:      "test-task-2",
			setupTask:   true,
			taskStatus:  types.TaskStatusRunning,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:        "valid GET - succeeded task",
			method:      http.MethodGet,
			taskID:      "test-task-3",
			setupTask:   true,
			taskStatus:  types.TaskStatusSucceeded,
			wantStatus:  http.StatusOK,
			checkFields: true,
		},
		{
			name:       "invalid method - POST not allowed",
			method:     http.MethodPost,
			taskID:     "test-task-4",
			setupTask:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - PUT not allowed",
			method:     http.MethodPut,
			taskID:     "test-task-5",
			setupTask:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "invalid method - DELETE not allowed",
			method:     http.MethodDelete,
			taskID:     "test-task-6",
			setupTask:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing task ID",
			method:     http.MethodGet,
			taskID:     "",
			setupTask:  false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "task not found",
			method:     http.MethodGet,
			taskID:     "nonexistent-task",
			setupTask:  false,
			wantStatus: http.StatusNotFound,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := taskstore.NewStore()
			handler := NewHandler(store)

			if tt.setupTask {
				task := &types.Task{
					ID: tt.taskID,
					Route: types.Route{
						Prev: []string{},
						Curr: "actor1",
						Next: []string{"actor2"},
					},
					TotalActors: 2,
				}
				if err := store.Create(task); err != nil {
					t.Fatalf("Failed to create test task: %v", err)
				}

				if tt.taskStatus != types.TaskStatusPending {
					update := types.TaskUpdate{
						ID:        tt.taskID,
						Status:    tt.taskStatus,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update task status: %v", err)
					}
				}
			}

			req := httptest.NewRequest(tt.method, "/mesh/"+tt.taskID, nil)
			rr := httptest.NewRecorder()

			handler.HandleMeshStatus(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleMeshStatus() status = %v, want %v", rr.Code, tt.wantStatus)
			}

			if tt.checkFields && tt.wantStatus == http.StatusOK {
				var task types.Task
				if err := json.NewDecoder(rr.Body).Decode(&task); err != nil {
					t.Fatalf("Failed to decode response: %v", err)
				}

				if task.ID != tt.taskID {
					t.Errorf("Task ID = %v, want %v", task.ID, tt.taskID)
				}
				if task.Status != tt.taskStatus {
					t.Errorf("Task status = %v, want %v", task.Status, tt.taskStatus)
				}
			}
		})
	}
}

// TestHandleMeshActive tests the GET /mesh/{id}/active endpoint
func TestHandleMeshActive(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		taskID     string
		setupTask  bool
		taskStatus types.TaskStatus
		wantStatus int
		wantActive bool
	}{
		{
			name:       "active task - pending",
			method:     http.MethodGet,
			taskID:     "test-active-1",
			setupTask:  true,
			taskStatus: types.TaskStatusPending,
			wantStatus: http.StatusOK,
			wantActive: true,
		},
		{
			name:       "active task - running",
			method:     http.MethodGet,
			taskID:     "test-active-2",
			setupTask:  true,
			taskStatus: types.TaskStatusRunning,
			wantStatus: http.StatusOK,
			wantActive: true,
		},
		{
			name:       "inactive task - succeeded",
			method:     http.MethodGet,
			taskID:     "test-active-3",
			setupTask:  true,
			taskStatus: types.TaskStatusSucceeded,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
		{
			name:       "inactive task - failed",
			method:     http.MethodGet,
			taskID:     "test-active-4",
			setupTask:  true,
			taskStatus: types.TaskStatusFailed,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
		{
			name:       "invalid method - POST not allowed",
			method:     http.MethodPost,
			taskID:     "test-active-5",
			setupTask:  true,
			taskStatus: types.TaskStatusPending,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "empty task ID path",
			method:     http.MethodGet,
			taskID:     "",
			setupTask:  false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "task not found - inactive",
			method:     http.MethodGet,
			taskID:     "nonexistent",
			setupTask:  false,
			wantStatus: http.StatusGone,
			wantActive: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := taskstore.NewStore()
			handler := NewHandler(store)

			if tt.setupTask {
				task := &types.Task{
					ID: tt.taskID,
					Route: types.Route{
						Prev: []string{},
						Curr: "actor1",
						Next: []string{},
					},
				}
				if err := store.Create(task); err != nil {
					t.Fatalf("Failed to create test task: %v", err)
				}

				if tt.taskStatus != types.TaskStatusPending {
					update := types.TaskUpdate{
						ID:        tt.taskID,
						Status:    tt.taskStatus,
						Timestamp: time.Now(),
					}
					if err := store.Update(update); err != nil {
						t.Fatalf("Failed to update task status: %v", err)
					}
				}
			}

			var req *http.Request
			if tt.taskID == "" {
				req = httptest.NewRequest(tt.method, "/mesh//active", nil)
			} else {
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/active", nil)
			}
			rr := httptest.NewRecorder()

			handler.HandleMeshActive(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleMeshActive() status = %v, want %v", rr.Code, tt.wantStatus)
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

// TestHandleMeshFinal tests the POST /mesh/{id}/final endpoint
func TestHandleMeshFinal(t *testing.T) {
	tests := []struct {
		name           string
		method         string
		taskID         string
		setupTask      bool
		finalUpdate    interface{}
		wantStatus     int
		wantTaskStatus types.TaskStatus
		checkUpdate    bool
	}{
		{
			name:      "valid success - basic",
			method:    http.MethodPost,
			taskID:    "test-final-1",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-1",
				"status": "succeeded",
				"result": map[string]interface{}{"output": "success"},
			},
			wantStatus:     http.StatusOK,
			wantTaskStatus: types.TaskStatusSucceeded,
			checkUpdate:    true,
		},
		{
			name:      "valid success - with S3 URI",
			method:    http.MethodPost,
			taskID:    "test-final-2",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-2",
				"status": "succeeded",
				"result": map[string]interface{}{"data": "result"},
				"metadata": map[string]interface{}{
					"s3_uri": "s3://bucket/key",
				},
			},
			wantStatus:     http.StatusOK,
			wantTaskStatus: types.TaskStatusSucceeded,
			checkUpdate:    true,
		},
		{
			name:      "valid failure - with error message",
			method:    http.MethodPost,
			taskID:    "test-final-3",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-3",
				"status": "failed",
				"error":  "Processing error occurred",
			},
			wantStatus:     http.StatusOK,
			wantTaskStatus: types.TaskStatusFailed,
			checkUpdate:    true,
		},
		{
			name:      "valid failure - without error message",
			method:    http.MethodPost,
			taskID:    "test-final-4",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"id":     "test-final-4",
				"status": "failed",
			},
			wantStatus:     http.StatusOK,
			wantTaskStatus: types.TaskStatusFailed,
			checkUpdate:    true,
		},
		{
			name:       "invalid method - GET not allowed",
			method:     http.MethodGet,
			taskID:     "test-final-5",
			setupTask:  true,
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:      "invalid method - PUT not allowed",
			method:    http.MethodPut,
			taskID:    "test-final-6",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"status": "succeeded",
			},
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "missing task ID",
			method:     http.MethodPost,
			taskID:     "",
			setupTask:  false,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:        "invalid JSON body",
			method:      http.MethodPost,
			taskID:      "test-final-7",
			setupTask:   true,
			finalUpdate: "not valid json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:      "invalid status - unknown value",
			method:    http.MethodPost,
			taskID:    "test-final-8",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"job_id": "test-final-8",
				"status": "unknown_status",
			},
			wantStatus: http.StatusBadRequest,
		},
		{
			name:      "invalid status - empty string",
			method:    http.MethodPost,
			taskID:    "test-final-9",
			setupTask: true,
			finalUpdate: map[string]interface{}{
				"job_id": "test-final-9",
				"status": "",
			},
			wantStatus: http.StatusBadRequest,
		},
		{
			name:      "task not found",
			method:    http.MethodPost,
			taskID:    "nonexistent",
			setupTask: false,
			finalUpdate: map[string]interface{}{
				"job_id": "nonexistent",
				"status": "succeeded",
			},
			wantStatus: http.StatusInternalServerError,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := taskstore.NewStore()
			handler := NewHandler(store)

			if tt.setupTask {
				task := &types.Task{
					ID: tt.taskID,
					Route: types.Route{
						Prev: []string{},
						Curr: "actor1",
						Next: []string{},
					},
					Status: types.TaskStatusRunning,
				}
				if err := store.Create(task); err != nil {
					t.Fatalf("Failed to create test task: %v", err)
				}
			}

			var req *http.Request
			if tt.finalUpdate == nil {
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/final", nil)
			} else if bodyStr, ok := tt.finalUpdate.(string); ok {
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/final", bytes.NewReader([]byte(bodyStr)))
			} else {
				body, _ := json.Marshal(tt.finalUpdate)
				req = httptest.NewRequest(tt.method, "/mesh/"+tt.taskID+"/final", bytes.NewReader(body))
			}
			req.Header.Set("Content-Type", "application/json")

			rr := httptest.NewRecorder()
			handler.HandleMeshFinal(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("HandleMeshFinal() status = %v, want %v, body = %s", rr.Code, tt.wantStatus, rr.Body.String())
			}

			if tt.checkUpdate && tt.wantStatus == http.StatusOK {
				task, err := store.Get(tt.taskID)
				if err != nil {
					t.Fatalf("Failed to get updated task: %v", err)
				}

				if task.Status != tt.wantTaskStatus {
					t.Errorf("Task status = %v, want %v", task.Status, tt.wantTaskStatus)
				}

				if tt.wantTaskStatus == types.TaskStatusSucceeded && task.Result == nil {
					updateMap := tt.finalUpdate.(map[string]interface{})
					if _, hasResult := updateMap["result"]; hasResult {
						t.Error("Expected result to be set for succeeded task")
					}
				}

				if tt.wantTaskStatus == types.TaskStatusFailed {
					updateMap := tt.finalUpdate.(map[string]interface{})
					if errMsg, hasError := updateMap["error"].(string); hasError && errMsg != "" {
						if task.Error == "" {
							t.Error("Expected error message to be set")
						}
					}
				}
			}
		})
	}
}

func TestMeshPathRegex(t *testing.T) {
	tests := []struct {
		name        string
		path        string
		regex       string
		wantMatch   bool
		wantID      string
		description string
	}{
		{
			name:        "valid task status path",
			path:        "/mesh/abc-123",
			regex:       "status",
			wantMatch:   true,
			wantID:      "abc-123",
			description: "Should match /mesh/{id}",
		},
		{
			name:        "valid task stream path",
			path:        "/mesh/test-id-456/stream",
			regex:       "stream",
			wantMatch:   true,
			wantID:      "test-id-456",
			description: "Should match /mesh/{id}/stream",
		},
		{
			name:        "valid task active path",
			path:        "/mesh/uuid-789/active",
			regex:       "active",
			wantMatch:   true,
			wantID:      "uuid-789",
			description: "Should match /mesh/{id}/active",
		},
		{
			name:        "valid task progress path",
			path:        "/mesh/task-001/progress",
			regex:       "progress",
			wantMatch:   true,
			wantID:      "task-001",
			description: "Should match /mesh/{id}/progress",
		},
		{
			name:        "valid task final path",
			path:        "/mesh/final-test/final",
			regex:       "final",
			wantMatch:   true,
			wantID:      "final-test",
			description: "Should match /mesh/{id}/final",
		},
		{
			name:        "UUID format task ID",
			path:        "/mesh/550e8400-e29b-41d4-a716-446655440000",
			regex:       "status",
			wantMatch:   true,
			wantID:      "550e8400-e29b-41d4-a716-446655440000",
			description: "Should match UUID format IDs",
		},
		{
			name:        "empty task ID",
			path:        "/mesh//stream",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject empty task ID",
		},
		{
			name:        "missing task ID",
			path:        "/mesh/",
			regex:       "status",
			wantMatch:   false,
			description: "Should reject missing task ID",
		},
		{
			name:        "wrong suffix",
			path:        "/mesh/test-id/wrong",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject wrong suffix",
		},
		{
			name:        "extra path segments",
			path:        "/mesh/test-id/stream/extra",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject extra path segments",
		},
		{
			name:        "task ID with slashes",
			path:        "/mesh/id/with/slashes/stream",
			regex:       "stream",
			wantMatch:   false,
			description: "Should reject task ID containing slashes",
		},
		{
			name:        "status path with trailing slash",
			path:        "/mesh/test-id/",
			regex:       "status",
			wantMatch:   false,
			description: "Should reject trailing slash",
		},
		{
			name:        "stream path without trailing slash",
			path:        "/mesh/test-id/stream",
			regex:       "stream",
			wantMatch:   true,
			wantID:      "test-id",
			description: "Should match stream path without trailing slash",
		},
		{
			name:        "alphanumeric with hyphens and underscores",
			path:        "/mesh/test_id-123_abc/progress",
			regex:       "progress",
			wantMatch:   true,
			wantID:      "test_id-123_abc",
			description: "Should match IDs with hyphens and underscores",
		},
		{
			name:        "numeric only ID",
			path:        "/mesh/123456/final",
			regex:       "final",
			wantMatch:   true,
			wantID:      "123456",
			description: "Should match numeric only IDs",
		},
	}

	regexMap := map[string]*regexp.Regexp{
		"status":   meshPathRegex,
		"stream":   meshStreamPathRegex,
		"active":   meshActivePathRegex,
		"progress": meshProgressPathRegex,
		"final":    meshFinalPathRegex,
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
					t.Errorf("Expected regex to capture task ID, but got %d matches", len(matches))
					return
				}
				gotID := matches[1]
				if gotID != tt.wantID {
					t.Errorf("Expected task ID %q, got %q", tt.wantID, gotID)
				}
			} else {
				if matches != nil {
					t.Errorf("Expected path %q to NOT match regex, but it did. %s. Captured ID: %q", tt.path, tt.description, matches[1])
				}
			}
		})
	}
}

func TestMeshPathRegex_EdgeCases(t *testing.T) {
	store := taskstore.NewStore()
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
			path:        "/mesh//active",
			method:      http.MethodGet,
			handlerFunc: handler.HandleMeshActive,
			wantStatus:  http.StatusBadRequest,
			description: "Regex should reject double slashes",
		},
		{
			name:        "malformed path missing prefix",
			path:        "/wrong/test-id/stream",
			method:      http.MethodGet,
			handlerFunc: handler.HandleMeshStream,
			wantStatus:  http.StatusBadRequest,
			description: "Regex should reject wrong prefix",
		},
		{
			name:        "path with query parameters",
			path:        "/mesh/test-id?foo=bar",
			method:      http.MethodGet,
			handlerFunc: handler.HandleMeshStatus,
			wantStatus:  http.StatusNotFound,
			description: "Query parameters are stripped by URL.Path, task not found",
		},
		{
			name:        "extremely long task ID",
			path:        "/mesh/" + strings.Repeat("a", 1000) + "/progress",
			method:      http.MethodPost,
			handlerFunc: handler.HandleMeshProgress,
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

func TestHandleMeshCreate(t *testing.T) {
	tests := []struct {
		name        string
		method      string
		requestBody map[string]interface{}
		wantStatus  int
		wantTask    bool
	}{
		{
			name:   "valid fanout task creation",
			method: http.MethodPost,
			requestBody: map[string]interface{}{
				"id":        "abc-123-1",
				"parent_id": "abc-123",
				"prev":      []string{"actor0"},
				"curr":      "actor1",
				"next":      []string{},
			},
			wantStatus: http.StatusCreated,
			wantTask:   true,
		},
		{
			name:   "missing id field",
			method: http.MethodPost,
			requestBody: map[string]interface{}{
				"parent_id": "abc-123",
				"prev":      []string{},
				"curr":      "actor1",
				"next":      []string{},
			},
			wantStatus: http.StatusBadRequest,
			wantTask:   false,
		},
		{
			name:        "invalid json",
			method:      http.MethodPost,
			requestBody: nil,
			wantStatus:  http.StatusBadRequest,
			wantTask:    false,
		},
		{
			name:        "wrong method GET",
			method:      http.MethodGet,
			requestBody: nil,
			wantStatus:  http.StatusMethodNotAllowed,
			wantTask:    false,
		},
		{
			name:        "wrong method PUT",
			method:      http.MethodPut,
			requestBody: nil,
			wantStatus:  http.StatusMethodNotAllowed,
			wantTask:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			store := taskstore.NewStore()
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

			req := httptest.NewRequest(tt.method, "/tasks", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			handler.HandleMeshCreate(rr, req)

			if rr.Code != tt.wantStatus {
				t.Errorf("got status %d, want %d", rr.Code, tt.wantStatus)
			}

			// Verify task was created if expected
			if tt.wantTask {
				taskID := tt.requestBody["id"].(string)
				task, err := store.Get(taskID)
				if err != nil {
					t.Errorf("Task not found: %v", err)
				}
				if task == nil {
					t.Error("Task is nil")
				} else {
					if task.ID != taskID {
						t.Errorf("Task ID = %v, want %v", task.ID, taskID)
					}
					parentIDStr := tt.requestBody["parent_id"].(string)
					if task.ParentID == nil || *task.ParentID != parentIDStr {
						t.Errorf("Task ParentID = %v, want %v", task.ParentID, parentIDStr)
					}
					if task.Status != types.TaskStatusPending {
						t.Errorf("Task Status = %v, want Pending", task.Status)
					}
				}
			}
		})
	}
}

func TestHandleMeshCreate_DuplicateID(t *testing.T) {
	store := taskstore.NewStore()
	handler := NewHandler(store)

	// Create first task
	task := &types.Task{
		ID:     "abc-123-1",
		Status: types.TaskStatusPending,
		Route:  types.Route{Prev: []string{}, Curr: "actor1", Next: []string{}},
	}
	if err := store.Create(task); err != nil {
		t.Fatalf("Failed to create task: %v", err)
	}

	// Try to create duplicate
	requestBody := map[string]interface{}{
		"id":        "abc-123-1",
		"parent_id": "abc-123",
		"prev":      []string{"actor0"},
		"curr":      "actor1",
		"next":      []string{},
	}

	body, _ := json.Marshal(requestBody)
	req := httptest.NewRequest(http.MethodPost, "/tasks", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	handler.HandleMeshCreate(rr, req)

	// Should return error
	if rr.Code == http.StatusCreated {
		t.Error("Should not allow duplicate task ID")
	}
}
