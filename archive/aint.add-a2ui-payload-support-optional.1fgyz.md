---
title: Add A2UI payload support (optional)
status: open
priority: 4
---

Support A2UI declarative UI payloads in task artifacts.

## Overview
A2UI is Google's declarative UI format that allows agents to generate rich, interactive UIs without executing arbitrary code. This is OPTIONAL and only needed if actors generate dynamic UIs.

## How A2UI Works
1. Actor generates A2UI JSON payload (component tree)
2. Gateway delivers via A2A TaskArtifactUpdateEvent or AG-UI CustomEvent
3. Frontend renderer maps abstract components to native widgets

## A2UI Payload Format
```json
{
  "components": [
    {
      "id": "card-1",
      "type": "card",
      "properties": {
        "title": "Weather Report",
        "content": "72°F, Sunny"
      }
    },
    {
      "id": "btn-1", 
      "type": "button",
      "properties": {
        "label": "Refresh",
        "action": "refresh_weather"
      }
    }
  ]
}
```

## Implementation
- Detect A2UI payloads by media_type: application/a2ui+json
- Deliver via A2A: TaskArtifactUpdateEvent
- Deliver via AG-UI: CustomEvent with name: A2UI_COMPONENT
- No validation needed (frontend handles rendering)

## Testing
- Unit test for A2UI detection
- Integration test with A2UI payload

## References
- https://a2ui.org/
- https://github.com/google/A2UI


## Notes

## A2UI Protocol Research (2026-01-28)

### Overview
A2UI (Agent to UI) is Google's declarative UI protocol for agent-driven interfaces. Unlike AG-UI (event transport), A2UI is a JSON format for describing UI component trees.

**Status**: v0.8 Public Preview (December 2025)
**License**: Apache 2.0

### Core Design Principles

1. **Security First**: Declarative data format, not executable code. Client maintains catalog of pre-approved components.

2. **LLM-Friendly**: Flat list of components with ID references. Easy for LLMs to generate incrementally.

3. **Framework-Agnostic**: Separates UI structure from implementation. Maps to React, Flutter, SwiftUI, etc.

### How A2UI Works

1. **Generation**: Agent generates A2UI JSON payload
2. **Transport**: Sent via A2A or AG-UI
3. **Resolution**: Client's A2UI Renderer parses JSON
4. **Rendering**: Maps abstract components to native widgets

### A2UI Payload Format

```json
{
  "components": [
    {
      "id": "card-1",
      "type": "card",
      "properties": {
        "title": "Weather Report",
        "content": "72°F, Sunny"
      },
      "children": ["btn-1"]
    },
    {
      "id": "btn-1",
      "type": "button",
      "properties": {
        "label": "Refresh",
        "action": "refresh_weather"
      }
    }
  ],
  "root": "card-1"
}
```

### Component Types
- Standard form components (text-field, button, checkbox)
- Layout components (card, container, grid)
- Custom components (charts, maps, etc.)
- Interactive components with actions

### Transport via A2A
```json
{
  "type": "TaskArtifactUpdateEvent",
  "task_id": "task-123",
  "artifact": {
    "artifact_id": "ui-1",
    "name": "weather-widget",
    "parts": [
      {
        "data": {"components": [...]},
        "media_type": "application/a2ui+json"
      }
    ]
  }
}
```

### Transport via AG-UI
```json
{
  "type": "CUSTOM",
  "name": "A2UI_COMPONENT",
  "value": {
    "components": [...],
    "root": "card-1"
  }
}
```

### Relationship to Other Protocols
- **A2A**: Carries A2UI as artifact payload
- **AG-UI**: Carries A2UI as CustomEvent
- **MCP**: Not directly related (tool protocol)

### Implementation Priority
A2UI is OPTIONAL for Asya Gateway because:
1. Most actors return text/JSON, not UI components
2. Requires frontend A2UI renderer
3. Only needed for rich generative UI use cases

### References
- https://a2ui.org/
- https://github.com/google/A2UI
- https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/


_Migrated from beads `asya-53w`_
