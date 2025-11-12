# MCP Protocol Compliance Tests

Behavioral validation tests for Asya🎭 Gateway's MCP (Model Context Protocol) implementation.

## What Is Tested

✅ MCP protocol compliance (initialize, tools/list, tools/call)
✅ CallToolResult response structure (content array with valid types)
✅ Error handling (isError flag instead of protocol-level errors)
✅ Parameter validation (required/optional parameters)
✅ Multiple protocol versions (2024-11-05, 2025-03-26)
✅ Integration with envelope system

## Running Tests

```bash
# Run all tests
make test

# Show coverage
make cov

# Clean up
make clean
```

## Custom Options

```bash
# Debug mode
make test ASYA_LOG_LEVEL=DEBUG PYTEST_OPTS="-vv -s"

# Test different protocol version
make test PROTOCOL_VERSION=2025-03-26
```

## Test Structure

- `tests/test_mcp_compliance.py` - Main pytest test suite
- `config/tools.yml` - Test tool definitions for gateway
- `docker-compose.yml` - Test environment (gateway + postgres)

## Expected Results

All tests validate that the gateway:
- Returns proper MCP JSON-RPC 2.0 responses
- Uses valid content types (text/image/audio/resource)
- Reports tool errors with `isError=true` in the result
- Validates parameters correctly
- Creates envelopes from tool calls

## See Also

- [MCP Specification](https://modelcontextprotocol.io/specification)
- Gateway functional tests: `../gateway/`
- Integration tests: `../../integration/gateway-actors/`
