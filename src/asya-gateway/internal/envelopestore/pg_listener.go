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

// TaskEventsChannel is the unified PG NOTIFY channel for all mesh-to-API events.
const TaskEventsChannel = "task_events"

// Event type prefixes in the notification payload.
const (
	eventTypeFly      = "fly"
	eventTypeProgress = "progress"
	eventTypeFinal    = "final"
)

// parseNotification splits a "task_id:type:payload_json" notification.
func parseNotification(raw string) (taskID, eventType, payload string, ok bool) {
	// First colon separates task_id
	idx1 := strings.IndexByte(raw, ':')
	if idx1 <= 0 {
		return "", "", "", false
	}
	rest := raw[idx1+1:]
	// Second colon separates event type from payload
	idx2 := strings.IndexByte(rest, ':')
	if idx2 <= 0 {
		return "", "", "", false
	}
	return raw[:idx1], rest[:idx2], rest[idx2+1:], true
}

// StartEventListener runs a LISTEN loop on a dedicated PG connection.
// Dispatches received notifications to in-process subscribers.
// Blocks until ctx is canceled. Reconnects on connection errors.
func (s *PgStore) StartEventListener(ctx context.Context, connString string) {
	for {
		if err := s.listenLoop(ctx, connString); err != nil {
			if ctx.Err() != nil {
				return
			}
			slog.Warn("Event listener connection lost, reconnecting", "error", err)
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

	if _, err := conn.Exec(ctx, "LISTEN "+TaskEventsChannel); err != nil {
		return err
	}

	slog.Info("Event listener started", "channel", TaskEventsChannel)

	for {
		notification, err := conn.WaitForNotification(ctx)
		if err != nil {
			return err
		}

		taskID, eventType, payload, ok := parseNotification(notification.Payload)
		if !ok {
			slog.Warn("Event listener: malformed notification", "payload", notification.Payload)
			continue
		}

		s.dispatchEvent(taskID, eventType, payload)
	}
}

// dispatchEvent routes a parsed notification to the appropriate subscriber format.
func (s *PgStore) dispatchEvent(taskID, eventType, payload string) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var update types.EnvelopeUpdate

	switch eventType {
	case eventTypeFly:
		update = types.EnvelopeUpdate{
			ID:             taskID,
			Status:         types.EnvelopeStatusRunning,
			PartialPayload: json.RawMessage(payload),
			Timestamp:      time.Now(),
		}

	case eventTypeProgress, eventTypeFinal:
		if err := json.Unmarshal([]byte(payload), &update); err != nil {
			slog.Warn("Event listener: failed to unmarshal update",
				"task_id", taskID, "type", eventType, "error", err)
			return
		}
		update.ID = taskID

	default:
		slog.Warn("Event listener: unknown event type", "task_id", taskID, "type", eventType)
		return
	}

	s.notifyListeners(update)
}

// dispatchFLY dispatches a FLY payload to in-process subscribers.
// Kept for backward compatibility with NotifyFLY (in-process fallback).
func (s *PgStore) dispatchFLY(taskID string, payload string) {
	s.dispatchEvent(taskID, eventTypeFly, payload)
}
