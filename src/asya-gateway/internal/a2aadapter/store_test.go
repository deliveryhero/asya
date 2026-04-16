package a2aadapter_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	a2alib "github.com/a2aproject/a2a-go/a2a"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/a2aadapter"
	"github.com/deliveryhero/asya/asya-gateway/internal/meshclient"
)

func TestStoreAdapter_Get_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"id":         "task-001",
			"status":     "succeeded",
			"data":       json.RawMessage(`{"context_id":"ctx-1","result":{"accuracy":0.95},"message":"done"}`),
			"created_at": time.Now(),
			"updated_at": time.Now(),
		})
	}))
	defer srv.Close()

	mc := meshclient.New(srv.URL, srv.URL)
	store := a2aadapter.NewStoreAdapter(mc)

	task, version, err := store.Get(context.Background(), "task-001")
	require.NoError(t, err)
	assert.Equal(t, a2alib.TaskID("task-001"), task.ID)
	assert.Equal(t, a2alib.TaskStateCompleted, task.Status.State)
	assert.Equal(t, "ctx-1", task.ContextID)
	assert.NotEmpty(t, task.Artifacts)
	assert.NotZero(t, version)
}

func TestStoreAdapter_Get_NotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	mc := meshclient.New(srv.URL, srv.URL)
	store := a2aadapter.NewStoreAdapter(mc)

	_, _, err := store.Get(context.Background(), "missing")
	require.Error(t, err)
	assert.ErrorIs(t, err, a2alib.ErrTaskNotFound)
}

func TestStoreAdapter_Save_Noop(t *testing.T) {
	mc := meshclient.New("http://unused", "http://unused")
	store := a2aadapter.NewStoreAdapter(mc)

	version, err := store.Save(context.Background(), nil, nil, nil, a2alib.TaskVersion(42))
	require.NoError(t, err)
	assert.Equal(t, a2alib.TaskVersion(42), version)
}

func TestStoreAdapter_List_Empty(t *testing.T) {
	mc := meshclient.New("http://unused", "http://unused")
	store := a2aadapter.NewStoreAdapter(mc)

	resp, err := store.List(context.Background(), &a2alib.ListTasksRequest{PageSize: 10})
	require.NoError(t, err)
	assert.Empty(t, resp.Tasks)
	assert.Equal(t, 10, resp.PageSize)
}
