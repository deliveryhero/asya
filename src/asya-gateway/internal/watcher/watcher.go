package watcher

import (
	"context"
	"fmt"
	"hash/fnv"
	"log/slog"
	"os"
	"time"
)

// ReloadFunc is called when the watched directory contents change.
// The argument is the directory path. Errors are logged but do not stop the watcher.
type ReloadFunc func(dir string) error

// Watch polls dir every interval and calls reload when file fingerprint changes.
// Blocks until ctx is canceled. Run with `go watcher.Watch(...)`.
func Watch(ctx context.Context, dir string, interval time.Duration, reload ReloadFunc) {
	var last uint64
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			fp := DirFingerprint(dir)
			if fp == last {
				continue
			}
			if err := reload(dir); err != nil {
				slog.Error("Watcher reload failed", "dir", dir, "error", err)
				continue
			}
			last = fp
			slog.Info("Watcher reloaded config", "dir", dir)
		}
	}
}

// DirFingerprint returns FNV-64a hash of file names, mod times, and sizes.
func DirFingerprint(dir string) uint64 {
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
