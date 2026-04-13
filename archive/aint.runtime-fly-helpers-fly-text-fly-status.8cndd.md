---
title: Runtime FLY helpers (fly_text, fly_status)
status: merged
priority: 2
parent: emmc5
---

## Objective

Add zero-dependency FLY helper functions to `asya_runtime.py` for common A2A streaming patterns.

## Scope

### 1. `fly_text()` helper

```python
def fly_text(text, artifact_id="stream-0", last=False):
    """Convenience: yield "FLY", fly_text("hello")"""
    return {
        "artifact_update": {
            "artifact": {"artifact_id": artifact_id, "parts": [{"text": text}]},
            "append": True,
            "last_chunk": last,
        }
    }
```

### 2. `fly_status()` helper

```python
def fly_status(message):
    """Convenience: yield "FLY", fly_status("Thinking...")"""
    return {
        "status_update": {
            "status": {
                "state": "WORKING",
                "message": {"role": "agent", "parts": [{"text": message}]},
            }
        }
    }
```

### 3. Integration

- Add to `src/asya-runtime/asya_runtime.py` (symlinked to Crossplane chart)
- Maintain Python 3.7+ compatibility (typing.Dict, typing.List)
- Zero external dependencies

## References

- RFC section 9.1 (Runtime helpers)

## Acceptance Criteria

- `fly_text()` returns correct A2A artifact_update structure
- `fly_status()` returns correct A2A status_update structure
- Works with `yield "FLY", fly_text(...)` pattern in generator handlers
- Unit tests in `src/asya-runtime/tests/`
- No new dependencies added
