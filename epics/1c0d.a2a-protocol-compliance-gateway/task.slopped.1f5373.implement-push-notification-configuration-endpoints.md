---
title: Implement push notification configuration endpoints
priority: 4 # backlog
type: task
---




Add A2A push notification configuration CRUD endpoints.

## Requirements
- POST /tasks/{task_id}/pushNotificationConfigs - Create config
- GET /tasks/{task_id}/pushNotificationConfigs/{id} - Get config
- GET /tasks/{task_id}/pushNotificationConfigs - List configs
- DELETE /tasks/{task_id}/pushNotificationConfigs/{id} - Delete config

## Config Format
```json
{
  "id": "config-123",
  "url": "https://webhook.example.com/a2a",
  "token": "secret-token",
  "events": ["TaskStatusUpdateEvent", "TaskArtifactUpdateEvent"]
}
```

## Implementation
- Add PushNotificationConfig model
- Store configs in PostgreSQL
- On task events, POST to configured webhooks
- Include auth token in webhook requests

## Webhook Payload
```json
{
  "task_id": "...",
  "event_type": "TaskStatusUpdateEvent",
  "data": {...}
}
```

## Error Handling
- PushNotificationNotSupportedError if feature disabled
- Retry failed webhooks with exponential backoff

## Testing
- Unit test for config CRUD
- Integration test for webhook delivery
- Test retry logic


---
_Migrated from beads `asya-ly9`_
