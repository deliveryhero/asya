---
title: Design cross-namespace actor routing
status: open
priority: 4 # backlog
type: task
---


Research and design how actors can route messages across namespaces. Current idea: 'actor-name' for same namespace, 'namespace/actor-name' for cross-namespace. Considerations: IAM/RBAC per namespace, queue naming convention (asya-{namespace}-{actor}), security implications. Low priority - agent-created ephemeral actors are far future.


---
_Migrated from beads `asya-1k0`_
