package mcp

import (
	"context"
	"testing"

	"github.com/deliveryhero/asya/asya-gateway/internal/queue"
	"github.com/deliveryhero/asya/asya-gateway/internal/taskstore"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// MockQueueClient implements queue.Client for testing
type MockQueueClient struct{}

func (m *MockQueueClient) SendMessage(ctx context.Context, task *types.Task) error {
	return nil
}

func (m *MockQueueClient) Receive(ctx context.Context, queueName string) (queue.QueueMessage, error) {
	return nil, nil
}

func (m *MockQueueClient) Ack(ctx context.Context, msg queue.QueueMessage) error {
	return nil
}

func (m *MockQueueClient) Close() error {
	return nil
}

func TestNewServer_Basic(t *testing.T) {
	taskStore := taskstore.NewStore()
	queueClient := &MockQueueClient{}

	server := NewServer(taskStore, queueClient, nil)

	if server == nil {
		t.Fatal("NewServer returned nil")
	}

	if server.mcpServer == nil {
		t.Fatal("MCP server not initialized")
	}

	if server.registry == nil {
		t.Error("Registry should be created for REST API support")
	}

	mcpServer := server.GetMCPServer()
	if mcpServer == nil {
		t.Fatal("GetMCPServer returned nil")
	}
}
