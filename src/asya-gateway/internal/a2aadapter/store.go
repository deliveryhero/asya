package a2aadapter

import (
	"context"
	"encoding/json"
	"log/slog"

	a2alib "github.com/a2aproject/a2a-go/a2a"

	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

// StoreAdapter wraps the mesh-api HTTP client to implement a2asrv.TaskStore.
type StoreAdapter struct {
	meshClient *meshclient.Client
}

// NewStoreAdapter creates a new store adapter.
func NewStoreAdapter(meshClient *meshclient.Client) *StoreAdapter {
	return &StoreAdapter{meshClient: meshClient}
}

// Save translates an A2A event into a mesh-api update.
// Artifact events are ephemeral and not persisted.
// The mesh-api is the source of truth and receives status updates from
// sidecars directly. The A2A adapter only reads state.
func (s *StoreAdapter) Save(_ context.Context, _ *a2alib.Task, _ a2alib.Event, _ *a2alib.Task, prevVersion a2alib.TaskVersion) (a2alib.TaskVersion, error) {
	return prevVersion, nil
}

// Get fetches task state from mesh-api and converts to A2A Task.
func (s *StoreAdapter) Get(ctx context.Context, taskID a2alib.TaskID) (*a2alib.Task, a2alib.TaskVersion, error) {
	status, err := s.meshClient.Get(ctx, string(taskID))
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
	if status.Status == "succeeded" && status.Data != nil {
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

// List is not supported in the adapter (would require mesh-api list endpoint).
func (s *StoreAdapter) List(_ context.Context, req *a2alib.ListTasksRequest) (*a2alib.ListTasksResponse, error) {
	slog.Warn("A2A adapter List not implemented (requires mesh-api list)")
	return &a2alib.ListTasksResponse{
		Tasks:    []*a2alib.Task{},
		PageSize: req.PageSize,
	}, nil
}
