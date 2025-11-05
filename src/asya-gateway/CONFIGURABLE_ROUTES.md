# Configurable Routes Implementation

## Overview

Asya Gateway supports declarative tool configuration via YAML files. Define MCP tools, parameters, routing, and options without writing code.

## Features

✅ **Declarative YAML config** - No code changes to add/modify tools
✅ **All MCP parameter types** - string, number, boolean, array, object
✅ **Route templates** - Reusable pipeline definitions
✅ **Per-tool options** - progress, timeout, metadata
✅ **Global defaults** - Set once, override per-tool
✅ **Multi-file support** - Load all YAMLs from directory
✅ **Backward compatible** - Falls back to hardcoded tools

## Quick Start

See `config/README.md` for complete user documentation.

**Basic usage**:
```bash
export ASYA_CONFIG_PATH=config/routes.yaml
./bin/gateway
```

**Example config** (`config/routes.yaml`):
```yaml
tools:
  - name: my_tool
    parameters:
      input: {type: string, required: true}
    route: [processor]
```

## Implementation Architecture

### Components

1. **`internal/config/routes.go`**
   - Configuration structs and validation logic
   - Type-safe parameter definitions
   - Route resolution with template support

2. **`internal/config/loader.go`**
   - YAML file loading and parsing
   - Multi-file directory support
   - Configuration merging and validation

3. **`internal/mcp/registry.go`**
   - Dynamic MCP tool registration
   - Parameter conversion to MCP format
   - Tool handler creation with closures

4. **`cmd/gateway/main.go`**
   - Config loading on startup
   - Environment variable support (`ASYA_CONFIG_PATH`)

### File Structure

```
src/asya-gateway/
├── cmd/gateway/
│   └── main.go                    # Loads config and starts server
├── internal/
│   ├── config/
│   │   ├── routes.go              # Config structs and validation
│   │   ├── loader.go              # YAML loading and merging
│   │   ├── loader_test.go         # Unit tests
│   │   └── examples_test.go       # Example config validation
│   └── mcp/
│       ├── registry.go            # Dynamic tool registration
│       └── server.go              # MCP server (updated)
└── config/
    ├── README.md                  # User documentation
    └── examples/
        ├── routes-minimal.yaml    # Minimal starter example
        └── routes.yaml            # Comprehensive example
```

## Testing

```bash
cd src/asya-gateway
go test ./internal/config/... -v
```

All tests pass (config parsing, validation, merging, templates, examples).

## Parameter Types → MCP Mapping

| YAML Type | Maps To |
|-----------|---------|
| `string` | `mcp.WithString()` |
| `string` + `options` | `mcp.WithString(mcp.Enum())` |
| `number` / `integer` | `mcp.WithNumber()` |
| `boolean` | `mcp.WithBoolean()` |
| `array` | `mcp.WithArray()` with typed items |
| `object` | Generic (validated in handler) |

## Environment Variables

- `ASYA_CONFIG_PATH` - Path to config file or directory (optional, falls back to hardcoded tools)

## Validation

Startup validation checks:
- Unique tool names
- Valid routes (≥1 step, templates exist)
- Valid parameter types
- Required fields defined

## Future Extensions (Backward Compatible)

- `rateLimit`, `authentication`, `transforms`
- `conditionalRouting`, `parallelRouting`
- `hooks`, `circuit_breaker`

## Documentation

- **User Guide**: `config/README.md`
- **Examples**: `config/examples/routes*.yaml`
- **Code**: Inline godoc comments
