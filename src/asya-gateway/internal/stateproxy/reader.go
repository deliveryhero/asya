// Package stateproxy provides read access to persisted message state written by crew actors.
//
// Crew actors (x-sink, x-sump, x-pause) persist message envelopes to a state proxy mount
// (filesystem path backed by S3, GCS, or any other pluggable storage backend). This package
// provides a reader that the gateway uses to hydrate A2A GetTask responses with history and
// artifacts fetched from those persisted envelopes.
//
// File path convention (set by asya_crew/checkpointer.py):
//
//	{mountPath}/succeeded/{taskID}.json   - successfully completed tasks (x-sink)
//	{mountPath}/failed/{taskID}.json      - failed tasks (x-sink / x-sump)
//	{mountPath}/paused/{taskID}.json      - paused tasks waiting for input (x-pause)
//
// The persisted JSON structure is:
//
//	{
//	  "id": "task-uuid",
//	  "route": { "prev": [...], "curr": "...", "next": [...] },
//	  "payload": { "a2a": { "task": { "history": [...], "artifacts": [...] } }, ... },
//	  "status": { "phase": "succeeded" }   // optional
//	}
package stateproxy

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Reader reads persisted envelope state from a state proxy mount.
type Reader interface {
	// ReadPayload reads the persisted envelope payload for a task with the given prefix.
	// prefix is one of "succeeded", "failed", or "paused".
	// Returns nil, nil if the file does not exist (task not persisted yet or wrong prefix).
	ReadPayload(ctx context.Context, prefix, taskID string) (map[string]any, error)
}

// persistedEnvelope is the JSON structure written by crew actors to the state proxy.
type persistedEnvelope struct {
	Payload map[string]any `json:"payload"`
}

// FileReader reads persisted message state from a local filesystem state proxy mount.
// The filesystem is typically provided by a state proxy connector sidecar (backed by S3, GCS, etc.),
// but any writable filesystem path works — including a shared Docker volume in integration tests.
type FileReader struct {
	mountPath string
}

// NewFileReader creates a FileReader rooted at mountPath.
func NewFileReader(mountPath string) *FileReader {
	return &FileReader{mountPath: mountPath}
}

// ReadPayload reads {mountPath}/{prefix}/{taskID}.json and returns its payload field.
// Returns nil, nil when the file does not exist.
func (r *FileReader) ReadPayload(_ context.Context, prefix, taskID string) (map[string]any, error) {
	// filepath.Base guards against path traversal in taskID (e.g. "../../etc/passwd")
	safeID := filepath.Base(taskID)
	path := filepath.Join(r.mountPath, prefix, safeID+".json")

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("read state proxy file %s: %w", path, err)
	}

	var env persistedEnvelope
	if err := json.Unmarshal(data, &env); err != nil {
		return nil, fmt.Errorf("parse state proxy file %s: %w", path, err)
	}

	return env.Payload, nil
}
