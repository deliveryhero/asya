package toolstore

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"time"
)

// Watch polls dir every pollInterval and reloads the registry when file contents change.
// It logs errors but never stops — the previous cache is preserved on load failure.
// Call with go Watch(...) to run in the background.
func Watch(ctx context.Context, dir string, r *Registry, pollInterval time.Duration) {
	var last int64
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(pollInterval):
			fp := dirFingerprint(dir)
			if fp == last {
				continue
			}
			if err := r.LoadFromDir(dir); err != nil {
				slog.Error("Failed to reload tool registry from ConfigMap", "dir", dir, "error", err)
				continue
			}
			last = fp
			slog.Info("Tool registry reloaded from ConfigMap", "dir", dir, "tools", len(r.All()))
		}
	}
}

// dirFingerprint returns a sum of ModTime and Size for all non-directory entries
// in dir. A change in any file causes a different fingerprint.
func dirFingerprint(dir string) int64 {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	var sum int64
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		// Combine path hash, mod time, and size for a stable fingerprint
		for _, b := range []byte(filepath.Join(dir, entry.Name())) {
			sum += int64(b)
		}
		sum += info.ModTime().UnixNano() + info.Size()
	}
	return sum
}
