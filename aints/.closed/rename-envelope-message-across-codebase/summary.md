---
title: Rename Envelope to Message across codebase
priority: 2 # medium
---


Rename all references from 'Envelope' to 'Message' terminology. The term 'envelope' is internal jargon - 'message' is more intuitive and aligns with industry standards. This includes code, docs, and API endpoints.


---
**Close reason**: All envelope→message/task renames complete across Go sidecar, Go gateway, Python code, docs. 127 files changed. Deferred ASYA_HANDLER_MODE=envelope rename to asya-ob75.


--