---
title: Don't generate empty start/end routers
priority: 2 # medium
---
Whenever not needed (single actor flow, no real transformation), we should not generate entrypoint/exitpoint routers doing nothing.
