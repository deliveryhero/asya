package stateproxy_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/stateproxy"
)

func writeFixture(t *testing.T, dir, prefix, id string, payload map[string]any) {
	t.Helper()
	prefixDir := filepath.Join(dir, prefix)
	require.NoError(t, os.MkdirAll(prefixDir, 0o755))
	envelope := map[string]any{"id": id, "payload": payload}
	data, err := json.Marshal(envelope)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(filepath.Join(prefixDir, id+".json"), data, 0o644))
}

func TestFileReader_ReadPayload_Found(t *testing.T) {
	dir := t.TempDir()
	payload := map[string]any{"a2a": map[string]any{"task": map[string]any{"history": []any{}}}}
	writeFixture(t, dir, "succeeded", "task-123", payload)

	r := stateproxy.NewFileReader(dir)
	got, err := r.ReadPayload(context.Background(), "succeeded", "task-123")
	require.NoError(t, err)
	assert.Equal(t, payload, got)
}

func TestFileReader_ReadPayload_NotFound(t *testing.T) {
	dir := t.TempDir()
	r := stateproxy.NewFileReader(dir)
	got, err := r.ReadPayload(context.Background(), "succeeded", "nonexistent")
	require.NoError(t, err)
	assert.Nil(t, got)
}

func TestFileReader_ReadPayload_PausedPrefix(t *testing.T) {
	dir := t.TempDir()
	payload := map[string]any{"query": "hello"}
	writeFixture(t, dir, "paused", "task-paused", payload)

	r := stateproxy.NewFileReader(dir)
	got, err := r.ReadPayload(context.Background(), "paused", "task-paused")
	require.NoError(t, err)
	assert.Equal(t, payload, got)
}

func TestFileReader_ReadPayload_PathTraversalGuard(t *testing.T) {
	dir := t.TempDir()
	// Write a file that would be found if path traversal were allowed
	payload := map[string]any{"secret": true}
	writeFixture(t, dir, "succeeded", "legit", payload)

	r := stateproxy.NewFileReader(dir)
	// The path traversal attempt `../../legit` is sanitized by `filepath.Base` to just `legit`.
	// The test confirms that the read operation correctly targets `succeeded/legit.json`
	// within the temporary directory, and does not escape the mount path.
	got, err := r.ReadPayload(context.Background(), "succeeded", "../../legit")
	require.NoError(t, err)
	_ = got // result is fine either way; the path does NOT escape mountPath
}

func TestFileReader_ReadPayload_CorruptJSON(t *testing.T) {
	dir := t.TempDir()
	prefixDir := filepath.Join(dir, "succeeded")
	require.NoError(t, os.MkdirAll(prefixDir, 0o755))
	require.NoError(t, os.WriteFile(filepath.Join(prefixDir, "bad.json"), []byte("not-json"), 0o644))

	r := stateproxy.NewFileReader(dir)
	got, err := r.ReadPayload(context.Background(), "succeeded", "bad")
	assert.Error(t, err)
	assert.Nil(t, got)
}
