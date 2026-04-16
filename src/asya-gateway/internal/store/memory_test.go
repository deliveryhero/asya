package store

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func newTestMessage(id string, status types.MessageStatus) *types.Message {
	data, _ := json.Marshal(types.MessageData{Actor: "echo"})
	return &types.Message{
		ID:        id,
		Status:    status,
		Data:      data,
		CreatedAt: time.Now().UTC(),
		UpdatedAt: time.Now().UTC(),
	}
}

func TestMemoryStore_CreateAndGet(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	msg := newTestMessage("msg-1", types.MessageStatusPending)
	require.NoError(t, s.Create(ctx, msg))

	got, err := s.Get(ctx, "msg-1")
	require.NoError(t, err)
	assert.Equal(t, "msg-1", got.ID)
	assert.Equal(t, types.MessageStatusPending, got.Status)
}

func TestMemoryStore_GetNotFound(t *testing.T) {
	s := NewMemoryStore()
	_, err := s.Get(context.Background(), "nonexistent")
	assert.ErrorIs(t, err, ErrNotFound)
}

func TestMemoryStore_UpdateStatus_MonotonicOrdering(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	msg := newTestMessage("msg-1", types.MessageStatusPending)
	require.NoError(t, s.Create(ctx, msg))

	// Forward: pending -> running (ok)
	require.NoError(t, s.UpdateStatus(ctx, "msg-1", types.MessageStatusRunning, nil))
	got, _ := s.Get(ctx, "msg-1")
	assert.Equal(t, types.MessageStatusRunning, got.Status)

	// Backward: running -> pending (rejected)
	err := s.UpdateStatus(ctx, "msg-1", types.MessageStatusPending, nil)
	assert.ErrorIs(t, err, ErrStaleStatus)

	// Forward: running -> succeeded (ok)
	require.NoError(t, s.UpdateStatus(ctx, "msg-1", types.MessageStatusSucceeded, nil))
	got, _ = s.Get(ctx, "msg-1")
	assert.Equal(t, types.MessageStatusSucceeded, got.Status)

	// Terminal -> running (rejected)
	err = s.UpdateStatus(ctx, "msg-1", types.MessageStatusRunning, nil)
	assert.ErrorIs(t, err, ErrStaleStatus)
}

func TestMemoryStore_UpdateStatus_WithData(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	msg := newTestMessage("msg-1", types.MessageStatusPending)
	require.NoError(t, s.Create(ctx, msg))

	newData := json.RawMessage(`{"actor":"train","progress":50}`)
	require.NoError(t, s.UpdateStatus(ctx, "msg-1", types.MessageStatusRunning, newData))

	got, _ := s.Get(ctx, "msg-1")
	assert.JSONEq(t, `{"actor":"train","progress":50}`, string(got.Data))
}

func TestMemoryStore_Delete(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	msg := newTestMessage("msg-1", types.MessageStatusPending)
	require.NoError(t, s.Create(ctx, msg))

	require.NoError(t, s.Delete(ctx, "msg-1"))
	_, err := s.Get(ctx, "msg-1")
	assert.ErrorIs(t, err, ErrNotFound)
}

func TestMemoryStore_DeleteNotFound(t *testing.T) {
	s := NewMemoryStore()
	err := s.Delete(context.Background(), "nonexistent")
	assert.ErrorIs(t, err, ErrNotFound)
}

func TestMemoryStore_List(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	// Create messages with different timestamps
	for i, id := range []string{"a", "b", "c"} {
		msg := newTestMessage(id, types.MessageStatusPending)
		msg.CreatedAt = time.Now().UTC().Add(time.Duration(i) * time.Second)
		require.NoError(t, s.Create(ctx, msg))
	}

	// List all
	msgs, total, err := s.List(ctx, types.ListParams{})
	require.NoError(t, err)
	assert.Equal(t, 3, total)
	assert.Len(t, msgs, 3)

	// List with limit
	msgs, total, err = s.List(ctx, types.ListParams{Limit: 2})
	require.NoError(t, err)
	assert.Equal(t, 3, total)
	assert.Len(t, msgs, 2)

	// List with offset
	msgs, _, err = s.List(ctx, types.ListParams{Offset: 2})
	require.NoError(t, err)
	assert.Len(t, msgs, 1)
}

func TestMemoryStore_ListFilterByStatus(t *testing.T) {
	s := NewMemoryStore()
	ctx := context.Background()

	require.NoError(t, s.Create(ctx, newTestMessage("a", types.MessageStatusPending)))
	require.NoError(t, s.Create(ctx, newTestMessage("b", types.MessageStatusRunning)))
	require.NoError(t, s.Create(ctx, newTestMessage("c", types.MessageStatusRunning)))

	msgs, total, err := s.List(ctx, types.ListParams{
		Filters: map[string]any{"status": "running"},
	})
	require.NoError(t, err)
	assert.Equal(t, 2, total)
	assert.Len(t, msgs, 2)
}

func TestMemoryStore_PubSub(t *testing.T) {
	s := NewMemoryStore()

	ch := s.Subscribe("msg-1")

	// Publish event
	event := types.Event{Type: "status", Status: types.MessageStatusRunning}
	s.Publish("msg-1", event)

	select {
	case got := <-ch:
		assert.Equal(t, types.MessageStatusRunning, got.Status)
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for event")
	}

	// Unsubscribe
	s.Unsubscribe("msg-1", ch)
	_, ok := <-ch
	assert.False(t, ok, "channel should be closed after unsubscribe")
}
