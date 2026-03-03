package mcp

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MockQueueClientWithError for testing queue failures
type MockQueueClientWithError struct {
	sendErr error
}

func (m *MockQueueClientWithError) SendMessage(ctx context.Context, task *types.Task) error {
	if m.sendErr != nil {
		return m.sendErr
	}
	return nil
}

func (m *MockQueueClientWithError) Receive(ctx context.Context, queueName string) (queue.QueueMessage, error) {
	return nil, nil
}

func (m *MockQueueClientWithError) Ack(ctx context.Context, msg queue.QueueMessage) error {
	return nil
}

func (m *MockQueueClientWithError) Close() error {
	return nil
}

// MockTaskStore for testing
type MockTaskStore struct {
	createErr error
	updateErr error
	tasks     map[string]*types.Task
}

func NewMockTaskStore() *MockTaskStore {
	return &MockTaskStore{
		tasks: make(map[string]*types.Task),
	}
}

func (m *MockTaskStore) Create(task *types.Task) error {
	if m.createErr != nil {
		return m.createErr
	}
	m.tasks[task.ID] = task
	return nil
}

func (m *MockTaskStore) Update(update types.TaskUpdate) error {
	if m.updateErr != nil {
		return m.updateErr
	}
	if task, ok := m.tasks[update.ID]; ok {
		task.Status = update.Status
		task.Error = update.Error
	}
	return nil
}

func (m *MockTaskStore) Get(id string) (*types.Task, error) {
	if task, ok := m.tasks[id]; ok {
		return task, nil
	}
	return nil, fmt.Errorf("task not found")
}

func (m *MockTaskStore) AddProgress(id string, progress types.ProgressUpdate) error {
	return nil
}

func (m *MockTaskStore) Delete(id string) error {
	delete(m.tasks, id)
	return nil
}

func (m *MockTaskStore) UpdateProgress(update types.TaskUpdate) error {
	return m.Update(update)
}

func (m *MockTaskStore) Subscribe(id string) chan types.TaskUpdate {
	return make(chan types.TaskUpdate)
}

func (m *MockTaskStore) Unsubscribe(id string, ch chan types.TaskUpdate) {
	close(ch)
}

func (m *MockTaskStore) IsActive(id string) bool {
	task, exists := m.tasks[id]
	if !exists {
		return false
	}
	return task.Status == types.TaskStatusPending || task.Status == types.TaskStatusRunning
}

func (m *MockTaskStore) GetUpdates(id string, since *time.Time) ([]types.TaskUpdate, error) {
	return []types.TaskUpdate{}, nil
}

func (m *MockTaskStore) Resume(id string) (*types.Task, error) {
	if task, ok := m.tasks[id]; ok {
		return task, nil
	}
	return nil, fmt.Errorf("task not found")
}

func (m *MockTaskStore) List(status *types.TaskStatus) ([]*types.Task, error) {
	return nil, nil
}

// TestNewRegistry tests registry initialization
func TestNewRegistry(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	registry := NewRegistry(nil, taskStore, queueClient)

	if registry == nil {
		t.Fatal("Expected non-nil registry")
	}
	if registry.taskStore != taskStore {
		t.Error("TaskStore not set correctly")
	}
	if registry.queueClient != queueClient {
		t.Error("QueueClient not set correctly")
	}
	if registry.handlers == nil {
		t.Error("Handlers map not initialized")
	}
}

// TestGetToolHandler tests handler retrieval
func TestGetToolHandler(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	registry := NewRegistry(nil, taskStore, queueClient)

	t.Run("non-existing tool returns nil", func(t *testing.T) {
		handler := registry.GetToolHandler("non_existing_tool")
		if handler != nil {
			t.Error("Expected nil handler for non-existing tool")
		}
	})
}
