package envelopestore

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/pkg/types"
	"github.com/jackc/pgx/v5"
)

const flyChannel = "fly"

// parseFLYNotification splits a "task_id:payload_json" notification.
func parseFLYNotification(raw string) (string, string, bool) {
	idx := strings.IndexByte(raw, ':')
	if idx <= 0 {
		return "", "", false
	}
	return raw[:idx], raw[idx+1:], true
}

// StartFLYListener runs a LISTEN loop on a dedicated PG connection.
// Dispatches received FLY notifications to in-process subscribers.
// Blocks until ctx is canceled. Reconnects on connection errors.
func (s *PgStore) StartFLYListener(ctx context.Context, connString string) {
	for {
		if err := s.listenLoop(ctx, connString); err != nil {
			if ctx.Err() != nil {
				return
			}
			slog.Warn("FLY listener connection lost, reconnecting", "error", err)
			select {
			case <-time.After(time.Second):
			case <-ctx.Done():
				return
			}
		}
	}
}

func (s *PgStore) listenLoop(ctx context.Context, connString string) error {
	conn, err := pgx.Connect(ctx, connString)
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close(ctx) }()

	if _, err := conn.Exec(ctx, "LISTEN "+flyChannel); err != nil {
		return err
	}

	slog.Info("FLY listener started", "channel", flyChannel)

	for {
		notification, err := conn.WaitForNotification(ctx)
		if err != nil {
			return err
		}

		taskID, payload, ok := parseFLYNotification(notification.Payload)
		if !ok {
			slog.Warn("FLY listener: malformed notification", "payload", notification.Payload)
			continue
		}

		s.dispatchFLY(taskID, payload)
	}
}

// dispatchFLY dispatches a FLY payload to in-process subscribers.
func (s *PgStore) dispatchFLY(taskID string, payload string) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	update := types.EnvelopeUpdate{
		ID:             taskID,
		Status:         types.EnvelopeStatusRunning,
		PartialPayload: json.RawMessage(payload),
		Timestamp:      time.Now(),
	}
	s.notifyListeners(update)
}
