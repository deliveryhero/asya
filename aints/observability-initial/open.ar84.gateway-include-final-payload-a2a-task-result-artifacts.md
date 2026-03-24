---
title: "Gateway: include final payload in A2A task result (artifacts)"
priority: 1 # high
---

x-sink reports completed status to gateway but doesn't include the flow output payload. The gateway stores generic 'Task completed successfully' message. Per A2A spec, the final payload should be returned as an artifact in the task result. Requires: x-sink sends payload in progress report, gateway stores as artifact, tasks/get returns artifacts.
