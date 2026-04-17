package watcher_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

func TestDirFingerprint_EmptyDir(t *testing.T) {
	dir := t.TempDir()
	fp := watcher.DirFingerprint(dir)
	// Empty dir with no entries hashes to FNV offset basis (non-zero)
	assert.NotEqual(t, uint64(0), fp)
}

func TestDirFingerprint_ChangesOnFileModification(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.yaml")
	require.NoError(t, os.WriteFile(path, []byte("v1"), 0o644))

	fp1 := watcher.DirFingerprint(dir)

	// Ensure mod time advances (filesystem granularity)
	time.Sleep(10 * time.Millisecond)
	require.NoError(t, os.WriteFile(path, []byte("v2-longer"), 0o644))

	fp2 := watcher.DirFingerprint(dir)
	assert.NotEqual(t, fp1, fp2)
}

func TestWatch_CallsReloadOnChange(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tools.yaml")
	require.NoError(t, os.WriteFile(path, []byte("initial"), 0o644))

	reloadCount := 0
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go watcher.Watch(ctx, dir, 50*time.Millisecond, func(d string) error {
		reloadCount++
		return nil
	})

	// Wait for initial detection
	time.Sleep(150 * time.Millisecond)
	assert.GreaterOrEqual(t, reloadCount, 1, "should detect initial state")

	initialCount := reloadCount

	// Modify file
	time.Sleep(10 * time.Millisecond)
	require.NoError(t, os.WriteFile(path, []byte("changed"), 0o644))

	// Wait for next poll
	time.Sleep(150 * time.Millisecond)
	assert.Greater(t, reloadCount, initialCount, "should detect file change")
}

func TestDirFingerprint_NonexistentDir(t *testing.T) {
	fp := watcher.DirFingerprint("/nonexistent/path")
	assert.Equal(t, uint64(0), fp)
}
