---
title: "Runtime: add fully qualified error type + MRO to error responses"
status: open
priority: 1 # high
type: task
---

Modify _error_response() in src/asya-runtime/asya_runtime.py to include fully qualified exception type and MRO chain.

Current: details.type = type(exc).__name__ (e.g., 'ValueError')
New: details.type = fully qualified name (e.g., 'json.decoder.JSONDecodeError')
New: details.mro = ancestor classes excluding self and object/BaseException

Implementation:
- In _error_response(), compute fqn = f'{module}.{qualname}' if module != 'builtins' else qualname
- Compute mro list from exc_type.__mro__[1:], filtering out object and BaseException
- Add 'mro' key to error details dict
- Update existing unit tests to verify new fields
- Add test for stdlib subclass (e.g., json.JSONDecodeError -> mro includes ValueError)
- Add test for user-defined subclass

Performance: __mro__ is O(1) cached tuple, negligible vs traceback.format_exception().
Backward compatible: sidecar currently ignores unknown fields in error response.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Runtime Changes section)


---
**Close reason**: Implemented FQN error type and MRO chain in _error_response()


---
_Migrated from beads `asya-u5rm`_
