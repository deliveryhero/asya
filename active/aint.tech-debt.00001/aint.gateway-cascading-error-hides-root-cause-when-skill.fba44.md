---
title: "Gateway: cascading error hides root cause when skill not found"
status: open
priority: 2
parent: 00001
---

When A2A message/send targets a skill that doesn't exist, the gateway fails at resolveSkill() before creating the envelope in the DB. It then tries to store the failure state, which also fails because the envelope was never created. The user sees 'failed to store failed task state: envelope not found' instead of the actual error 'skill not found'. Fix: return the resolveSkill error directly without trying to persist it.
