package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/store"
	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
)

// runBackstop ticks at the given interval and marks any non-terminal messages
// with an expired deadline_at as failed.
func runBackstop(ctx context.Context, msgStore store.MessageStore, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	slog.Info("SLA backstop started", "interval", interval)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			reapExpired(ctx, msgStore)
		}
	}
}

func reapExpired(ctx context.Context, msgStore store.MessageStore) {
	ids, err := msgStore.FindExpired(ctx)
	if err != nil {
		slog.Warn("backstop: FindExpired failed", "error", err)
		return
	}
	for _, id := range ids {
		data, _ := json.Marshal(map[string]any{"error": "task timed out"})
		err := msgStore.UpdateStatus(ctx, id, types.MessageStatusFailed, data)
		if err != nil && err != store.ErrStaleStatus {
			slog.Warn("backstop: UpdateStatus failed", "id", id, "error", err)
			continue
		}
		slog.Info("backstop: reaped expired task", "id", id)
		msgStore.Publish(id, types.Event{
			Type:   "status",
			Status: types.MessageStatusFailed,
			Data:   data,
		})
	}
}
