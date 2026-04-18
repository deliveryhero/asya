package a2aadapter

import (
	"context"
	"encoding/json"
	"sync"

	a2alib "github.com/a2aproject/a2a-go/a2a"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// StoreAdapter wraps the mesh-api HTTP client to implement a2asrv.TaskStore.
// It maintains an in-memory mapping from a2a task IDs to mesh-api message IDs,
// since the two systems use different ID spaces.
type StoreAdapter struct {
	meshClient *meshclient.Client
	mu         sync.RWMutex
	taskToMsg  map[a2alib.TaskID]string // a2a task ID → mesh-api message ID
}

// NewStoreAdapter creates a new store adapter.
func NewStoreAdapter(meshClient *meshclient.Client) *StoreAdapter {
	return &StoreAdapter{
		meshClient: meshClient,
		taskToMsg:  make(map[a2alib.TaskID]string),
	}
}

// RegisterTask stores the mapping from a2a task ID to mesh-api message ID.
// Called by the executor after creating a mesh message.
func (s *StoreAdapter) RegisterTask(a2aTaskID a2alib.TaskID, meshMsgID string) {
	s.mu.Lock()
	s.taskToMsg[a2aTaskID] = meshMsgID
	s.mu.Unlock()
}

// lookupMeshID returns the mesh-api message ID for a given a2a task ID.
func (s *StoreAdapter) lookupMeshID(a2aTaskID a2alib.TaskID) (string, bool) {
	s.mu.RLock()
	id, ok := s.taskToMsg[a2aTaskID]
	s.mu.RUnlock()
	return id, ok
}

// Save is a no-op since the mesh-api is the source of truth.
// We clear the task History to prevent the a2a-go library from accumulating
// Message objects (with ContentParts) that cause JSON encoding recursion
// (stack overflow) when the terminal EventOverride is serialized to SSE.
func (s *StoreAdapter) Save(_ context.Context, task *a2alib.Task, _ a2alib.Event, _ *a2alib.Task, prevVersion a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	if task != nil {
		task.History = nil
	}
	return prevVersion, nil
}

// Get fetches task state from mesh-api and converts to A2A Task.
func (s *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	meshID := string(taskID)
	if mapped, ok := s.lookupMeshID(taskID); ok {
		meshID = mapped
	}
	status, err := s.meshClient.Get(ctx, meshID)
	if err != nil {
		return nil, 0, a2alib.ErrTaskNotFound
	}

	a2aTask := &a2alib.Task{
		ID:        taskID,
		ContextID: "",
		Status: a2alib.TaskStatus{
			State: MeshStatusToA2A(status.Status),
		},
		Metadata: make(map[string]any),
	}

	// Extract context_id from data if present
	if status.Data != nil {
		var data map[string]any
		if json.Unmarshal(status.Data, &data) == nil {
			if cid, ok := data["context_id"].(string); ok {
				a2aTask.ContextID = cid
			}
			if msg, ok := data["message"].(string); ok && msg != "" {
				a2aTask.Status.Message = a2alib.NewMessage(a2alib.MessageRoleAgent,
					&a2alib.TextPart{Text: msg})
			}
		}
	}

	// Synthesize result artifact for succeeded tasks
	if status.Status == string(types.MessageStatusSucceeded) && status.Data != nil {
		var data map[string]any
		if json.Unmarshal(status.Data, &data) == nil {
			if result, ok := data["result"]; ok && result != nil {
				resultJSON, _ := json.Marshal(result)
				a2aTask.Artifacts = []*a2alib.Artifact{{
					ID:   a2alib.ArtifactID(resultArtifactID),
					Name: "Task result",
					Parts: a2alib.ContentParts{
						&a2alib.TextPart{Text: string(resultJSON)},
					},
				}}
			}
		}
	}

	version := a2alib.TaskVersion(status.UpdatedAt.UnixNano())
	return a2aTask, version, nil
}

// List returns tasks from the in-memory task ID registry.
// Only tasks that were dispatched through this adapter instance are returned.
func (s *StoreAdapter) List(ctx context.Context, req *a2alib.ListTasksRequest) (*a2alib.ListTasksResponse, error) {
	s.mu.RLock()
	msgIDs := make([]string, 0, len(s.taskToMsg))
	taskIDs := make([]a2alib.TaskID, 0, len(s.taskToMsg))
	for tid, mid := range s.taskToMsg {
		taskIDs = append(taskIDs, tid)
		msgIDs = append(msgIDs, mid)
	}
	s.mu.RUnlock()

	tasks := make([]*a2alib.Task, 0, len(msgIDs))
	for i, mid := range msgIDs {
		status, err := s.meshClient.Get(ctx, mid)
		if err != nil {
			continue
		}
		t := &a2alib.Task{
			ID:       taskIDs[i],
			Status:   a2alib.TaskStatus{State: MeshStatusToA2A(status.Status)},
			Metadata: make(map[string]any),
		}
		if status.Data != nil {
			var data map[string]any
			if json.Unmarshal(status.Data, &data) == nil {
				if cid, ok := data["context_id"].(string); ok {
					t.ContextID = cid
				}
			}
		}
		tasks = append(tasks, t)
	}
	return &a2alib.ListTasksResponse{
		Tasks:    tasks,
		PageSize: req.PageSize,
	}, nil
}
