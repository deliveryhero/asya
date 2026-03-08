package toolstore

import (
	"context"
	"fmt"
	"hash/fnv"
	"log/slog"
	"os"
	"time"
)

// Watch polls dir every pollInterval and reloads the registry when file contents change.
// It logs errors but never stops — the previous cache is preserved on load failure.
// Call with go Watch(...) to run in the background.
func Watch(ctx context.Context, dir string, r *Registry, pollInterval time.Duration) {
	var last uint64
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
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

// dirFingerprint returns a hash of sorted file names, mod times, and sizes for
// all non-directory entries in dir. Using FNV-64a avoids the collisions that
// simple integer summation is prone to (e.g. renames with similar byte values).
func dirFingerprint(dir string) uint64 {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	h := fnv.New64a()
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		_, _ = fmt.Fprintf(h, "%s:%d:%d\n", entry.Name(), info.ModTime().UnixNano(), info.Size())
	}
	return h.Sum64()
}
