---
title: Add A2A error response format
status: merged
priority: 2
tags:
  - pr:202
---

Implement A2A-compliant error responses.

## A2A Error Types
- TaskNotFoundError - 404 Task not found
- PushNotificationNotSupportedError - Push not available
- UnsupportedOperationError - Operation not supported
- ContentTypeNotSupportedError - Media type not supported
- VersionNotSupportedError - Protocol version unsupported

## Error Response Format
```json
{
  "error": {
    "code": "TaskNotFoundError",
    "message": "Task with ID 'xyz' not found",
    "details": {...}
  }
}
```

## HTTP Status Codes
- 400 Bad Request - Validation errors
- 401 Unauthorized - Missing/invalid auth
- 403 Forbidden - Insufficient permissions
- 404 Not Found - Resource not found
- 500 Internal Server Error - Server errors
- 503 Service Unavailable - Temporary unavailability

## Implementation
- Create error types in pkg/types/errors.go
- Add error handler middleware
- Return consistent error format

## Testing
- Unit test for each error type
- Integration test for error responses


_Migrated from beads `asya-71m`_
