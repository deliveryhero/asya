---
title: Implement Agent Card discovery endpoint
priority: 2 # medium
type: task
tags:
  - pr:202
---





Add GET /.well-known/a2a/agent-card endpoint that returns the Agent Card JSON.

## Requirements
- Serve at standard well-known URI path
- Return JSON with: name, description, version, protocol_versions
- Include supported_interfaces (REST endpoint URL)
- Declare capabilities: streaming=true, pushNotifications=true
- List security_schemes (bearer, oauth2, apiKey)
- Define default_input_modes and default_output_modes
- List skills (derived from tool configuration)

## Agent Card Structure
```json
{
  "name": "Asya Agent Network",
  "description": "Distributed AI agent orchestration",
  "version": "1.0.0",
  "protocol_versions": ["1.0"],
  "capabilities": {"streaming": true, "pushNotifications": true},
  "security_schemes": {...},
  "skills": [...]
}
```

## Implementation
- Add handler in internal/mcp/handlers.go
- Generate skills list from tool registry
- Make configurable via environment or config file

## Testing
- Unit test for Agent Card structure
- Integration test for endpoint accessibility


---
_Migrated from beads `asya-4c1`_
