# MCP Protocol Compliance Tests

This document describes the test suite for verifying that asya-gateway correctly implements the Model Context Protocol (MCP).

## Overview

The test suite consists of **unit tests** and **integration tests** that verify:
1. MCP server initialization and configuration
2. Tool registration from YAML configuration
3. Multiple tool support with various parameter types
4. Route templates and defaults
5. MCP protocol methods (initialize, tools/list, tools/call)
6. Parameter validation and type checking

## Test Files

### Unit Tests (`internal/mcp/server_test.go`)

Tests the MCP server creation and tool registration logic:

- **TestNewServer_WithoutConfig**: Verifies hardcoded tools are used when no config provided
- **TestNewServer_WithConfig**: Verifies tools are loaded from configuration
- **TestNewServer_WithMultipleTools**: Tests registration of multiple tools simultaneously
- **TestNewServer_WithRouteTemplates**: Tests route template resolution
- **TestNewServer_WithDefaults**: Tests global default settings for tools
- **TestNewServer_InvalidConfig**: Tests config validation (empty routes, duplicate names, etc.)

### Integration Tests (`test/integration/mcp_protocol_test.go`)

Tests MCP protocol compliance and HTTP endpoints:

- **TestMCPProtocol_Initialize**: Verifies MCP initialize handshake
  - Tests JSON-RPC 2.0 response format
  - Validates server info (name: "asya-gateway", version: "0.1.0")
  - Checks protocol version
  - Verifies server capabilities (tools support)

- **TestMCPProtocol_ListTools**: Verifies tools/list method
  - Tests tool enumeration
  - Validates tool structure (name, description, inputSchema)
  - Checks parameter definitions

- **TestMCPProtocol_CallTool**: Verifies tools/call method
  - Tests tool invocation
  - Validates job creation and queue submission

- **TestMCPProtocol_ParameterValidation**: Tests parameter validation
  - Required vs optional parameters
  - Parameter type checking

- **TestMCPProtocol_MultipleParameterTypes**: Tests all parameter types
  - String, number, boolean parameters
  - Array parameters with typed items
  - Complex nested parameters

## Running the Tests

### Run Unit Tests Only
```bash
make test-unit-gateway
# or
go test ./internal/mcp -v
```

### Run Integration Tests
```bash
go test -tags=integration ./test/integration -v -run TestMCPProtocol
```

### Run All Tests
```bash
make test-unit-gateway
make test-integration-gateway
```

## MCP Protocol Compliance

The tests verify compliance with the following MCP requirements:

### ✅ JSON-RPC 2.0
- Correct message format: `{"jsonrpc": "2.0", "id": ..., "method": ..., "params": ...}`
- Proper response structure: `{"jsonrpc": "2.0", "id": ..., "result": ...}`
- Error handling with standard error codes

### ✅ Initialize Method
- Protocol version negotiation
- Server info reporting (name, version)
- Capability advertisement (tools support)

### ✅ Tools Support
- `tools/list`: Enumerate available tools
- `tools/call`: Invoke tools with parameters
- Tool schema definition (name, description, inputSchema)
- Parameter types: string, number, boolean, array, object

### ✅ HTTP/SSE Transport
- HTTP POST endpoint at `/mcp`
- Server-Sent Events for streaming (via `NewStreamableHTTPServer`)
- Session management (handled by mcp-go library)

## Implementation Details

### MCP Library
The gateway uses `github.com/mark3labs/mcp-go v0.41.1`, a community implementation of the Model Context Protocol in Go.

### Key Components
- **MCP Server**: Created via `server.NewMCPServer()` with tools capability
- **Tool Registration**: Dynamic registration from YAML config via `AddTool()`
- **HTTP Handler**: `server.NewStreamableHTTPServer()` provides HTTP/SSE transport
- **Job Management**: Custom job store and RabbitMQ queue integration

### Tool Configuration
Tools are defined in YAML:

```yaml
tools:
  - name: my_tool
    description: Process data
    parameters:
      input:
        type: string
        required: true
      count:
        type: number
        default: 5
    route: [parser, processor, finalizer]
    progress: true
    timeout: 300
```

See `src/asya-gateway/config/README.md` for full configuration options.

## Test Coverage

| Component | Coverage |
|-----------|----------|
| Server initialization | ✅ Complete |
| Tool registration | ✅ Complete |
| Config loading | ✅ Complete |
| Route templates | ✅ Complete |
| Defaults | ✅ Complete |
| Parameter types | ✅ Complete |
| Initialize handshake | ✅ Complete |
| Tools enumeration | ✅ Complete |
| Tool invocation | ✅ Complete |
| Validation | ✅ Complete |

## Known Limitations

1. **HTTP Session Tests**: Some HTTP-based tests are skipped because the streamable-http transport requires SSE connection establishment for session management. Direct MCP server testing is used instead.

2. **Error Response Testing**: Full JSON-RPC error response testing through HTTP requires proper session setup.

## Future Enhancements

- [ ] Add E2E HTTP session tests with SSE connection
- [ ] Add tests for MCP progress notifications
- [ ] Add tests for tool timeout handling
- [ ] Add benchmarks for tool registration performance
- [ ] Add tests for concurrent tool invocations

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [mcp-go Library](https://github.com/mark3labs/mcp-go)
- [Asya Gateway README](../README.md)
- [Tool Configuration Guide](../config/README.md)
