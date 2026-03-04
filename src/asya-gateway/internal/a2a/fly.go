package a2a

// DetectFLYEventType inspects the top-level keys of a FLY payload dict
// and returns the A2A SSE event type.
//
// Mapping (RFC Section 9.5.3):
//
//	artifact_update key → "artifact_update"
//	status_update key   → "status_update"
//	message key         → "message"
//	anything else       → "partial" (legacy/non-A2A)
func DetectFLYEventType(payload map[string]any) string {
	if _, ok := payload["artifact_update"]; ok {
		return "artifact_update"
	}
	if _, ok := payload["status_update"]; ok {
		return "status_update"
	}
	if _, ok := payload["message"]; ok {
		return "message"
	}
	return "partial"
}
