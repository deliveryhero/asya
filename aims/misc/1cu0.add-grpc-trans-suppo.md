---
title: Add gRPC transport support
status: open
priority: 3 # low
type: task
---

Add gRPC as alternative transport for A2A protocol.

## Background
A2A v0.3 added gRPC support alongside HTTP+SSE. This enables:
- Bidirectional streaming
- Lower latency
- Better for internal service-to-service communication

## Requirements
- Implement A2A gRPC service definition
- Support unary calls (SendMessage, GetTask, etc.)
- Support server streaming (Subscribe)
- Support bidirectional streaming (optional)

## Proto Definition
```protobuf
service A2AService {
  rpc SendMessage(SendMessageRequest) returns (SendMessageResponse);
  rpc SendStreamingMessage(SendMessageRequest) returns (stream TaskEvent);
  rpc GetTask(GetTaskRequest) returns (Task);
  rpc ListTasks(ListTasksRequest) returns (ListTasksResponse);
  rpc CancelTask(CancelTaskRequest) returns (Task);
  rpc SubscribeToTask(SubscribeRequest) returns (stream TaskEvent);
}
```

## Implementation
- Generate Go code from proto
- Add gRPC server alongside HTTP
- Share handler logic with HTTP handlers
- Configure port via ASYA_GRPC_PORT

## Testing
- Unit test for gRPC handlers
- Integration test with gRPC client
- Performance comparison with HTTP

## Note
This is lower priority than HTTP implementation. Can be deferred to v2.


---
_Migrated from beads `asya-ybm`_
