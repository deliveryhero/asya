package consumer

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// mockQueueMessage implements queue.QueueMessage
type mockQueueMessage struct {
	body []byte
}

func (m *mockQueueMessage) Body() []byte        { return m.body }
func (m *mockQueueMessage) DeliveryTag() uint64 { return 0 }

// mockTaskStore implements taskstore.TaskStore (minimal)
type mockTaskStore struct {
	updates []types.TaskUpdate
}

func (s *mockTaskStore) Create(task *types.Task) error { return nil }

func (s *mockTaskStore) Get(id string) (*types.Task, error) { return nil, nil }

func (s *mockTaskStore) Update(update types.TaskUpdate) error {
	s.updates = append(s.updates, update)
	return nil
}

func (s *mockTaskStore) UpdateProgress(update types.TaskUpdate) error { return nil }

func (s *mockTaskStore) GetUpdates(id string, since *time.Time) ([]types.TaskUpdate, error) {
	return nil, nil
}

func (s *mockTaskStore) Subscribe(id string) chan types.TaskUpdate {
	return make(chan types.TaskUpdate, 1)
}

func (s *mockTaskStore) Unsubscribe(id string, ch chan types.TaskUpdate) {}

func (s *mockTaskStore) IsActive(id string) bool { return false }

// mockQueueClient implements queue.Client with all no-ops
type mockQueueClient struct{}

func (m *mockQueueClient) SendMessage(ctx context.Context, task *types.Task) error { return nil }

func (m *mockQueueClient) Receive(ctx context.Context, queueName string) (queue.QueueMessage, error) {
	return nil, nil
}

func (m *mockQueueClient) Ack(ctx context.Context, msg queue.QueueMessage) error { return nil }

func (m *mockQueueClient) Close() error { return nil }

// TestProcessMessage_StatusPhaseSucceeded verifies that a message with status.phase="succeeded"
// results in TaskStatusSucceeded being stored.
func TestProcessMessage_StatusPhaseSucceeded(t *testing.T) {
	store := &mockTaskStore{}
	c := &ResultConsumer{
		taskStore:   store,
		queueClient: &mockQueueClient{},
	}

	body, err := json.Marshal(map[string]interface{}{
		"id":      "task-succeed-1",
		"payload": map[string]interface{}{"result": "ok"},
		"status": map[string]interface{}{
			"phase": "succeeded",
		},
	})
	if err != nil {
		t.Fatalf("Failed to marshal message body: %v", err)
	}

	c.processMessage(context.Background(), &mockQueueMessage{body: body}, types.TaskStatusSucceeded)

	if len(store.updates) != 1 {
		t.Fatalf("Expected 1 update, got %d", len(store.updates))
	}
	if store.updates[0].Status != types.TaskStatusSucceeded {
		t.Errorf("Status = %v, want %v", store.updates[0].Status, types.TaskStatusSucceeded)
	}
}

// TestProcessMessage_StatusPhaseFailed_WithReason verifies that a message with
// status.phase="failed", status.reason, and status.error results in TaskStatusFailed
// with the error and reason properly populated.
func TestProcessMessage_StatusPhaseFailed_WithReason(t *testing.T) {
	store := &mockTaskStore{}
	c := &ResultConsumer{
		taskStore:   store,
		queueClient: &mockQueueClient{},
	}

	body, err := json.Marshal(map[string]interface{}{
		"id":      "task-fail-1",
		"payload": map[string]interface{}{},
		"status": map[string]interface{}{
			"phase":  "failed",
			"reason": "MaxRetriesExhausted",
			"error": map[string]interface{}{
				"type":    "ValueError",
				"message": "Something broke",
			},
		},
	})
	if err != nil {
		t.Fatalf("Failed to marshal message body: %v", err)
	}

	// Queue-name fallback is succeeded, but status.phase="failed" should override
	c.processMessage(context.Background(), &mockQueueMessage{body: body}, types.TaskStatusSucceeded)

	if len(store.updates) != 1 {
		t.Fatalf("Expected 1 update, got %d", len(store.updates))
	}

	update := store.updates[0]

	if update.Status != types.TaskStatusFailed {
		t.Errorf("Status = %v, want %v", update.Status, types.TaskStatusFailed)
	}
	if update.Error == "" {
		t.Error("Expected non-empty Error, got empty string")
	}
	if update.Message == "" {
		t.Error("Expected non-empty Message, got empty string")
	}
	// Reason should appear in the message
	if update.Message != "Task failed: MaxRetriesExhausted" {
		t.Errorf("Message = %q, want %q", update.Message, "Task failed: MaxRetriesExhausted")
	}
	// Error should contain both type and message
	if update.Error != "ValueError: Something broke" {
		t.Errorf("Error = %q, want %q", update.Error, "ValueError: Something broke")
	}
}

// TestProcessMessage_NonTerminalPhase_Skipped verifies that a message with a non-terminal
// status.phase results in no task store update (silently acked).
func TestProcessMessage_NonTerminalPhase_Skipped(t *testing.T) {
	store := &mockTaskStore{}
	c := &ResultConsumer{
		taskStore:   store,
		queueClient: &mockQueueClient{},
	}

	body, err := json.Marshal(map[string]interface{}{
		"id":      "task-nonterminal-1",
		"payload": map[string]interface{}{},
		"status": map[string]interface{}{
			"phase": "awaiting_approval",
		},
	})
	if err != nil {
		t.Fatalf("Failed to marshal message body: %v", err)
	}

	c.processMessage(context.Background(), &mockQueueMessage{body: body}, types.TaskStatusSucceeded)

	if len(store.updates) != 0 {
		t.Errorf("Expected 0 updates for non-terminal phase, got %d", len(store.updates))
	}
}

// TestProcessMessage_NoStatusField_FallsBackToQueueName verifies that when no status field
// is present, the queue-name-based status parameter is used (backward compatibility).
func TestProcessMessage_NoStatusField_FallsBackToQueueName(t *testing.T) {
	store := &mockTaskStore{}
	c := &ResultConsumer{
		taskStore:   store,
		queueClient: &mockQueueClient{},
	}

	body, err := json.Marshal(map[string]interface{}{
		"id":      "task-fallback-1",
		"payload": map[string]interface{}{"data": "value"},
	})
	if err != nil {
		t.Fatalf("Failed to marshal message body: %v", err)
	}

	// Pass TaskStatusSucceeded as the queue-name fallback
	c.processMessage(context.Background(), &mockQueueMessage{body: body}, types.TaskStatusSucceeded)

	if len(store.updates) != 1 {
		t.Fatalf("Expected 1 update, got %d", len(store.updates))
	}
	if store.updates[0].Status != types.TaskStatusSucceeded {
		t.Errorf("Status = %v, want %v", store.updates[0].Status, types.TaskStatusSucceeded)
	}
}
