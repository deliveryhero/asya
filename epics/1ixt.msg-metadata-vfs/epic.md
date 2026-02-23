---
title: Message Metadata Virtual Filesystem
status: slopped
priority: 2 # medium
type: epic
---

Replace ASYA_HANDLER_MODE=envelope with /tmp/msg/ virtual filesystem for message metadata access. Handlers use standard open() to read/write route and headers. Payload remains the function argument. Shared open() interception mechanism with /state/ (stateful actors). Supersedes the /tmp/msg/ portion of closed epic 1c84.handler-signature-redesign.
