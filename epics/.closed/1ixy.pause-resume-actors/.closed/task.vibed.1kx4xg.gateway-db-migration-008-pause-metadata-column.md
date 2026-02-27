---
title: "Gateway: DB migration 008 for pause_metadata column"
priority: 2 # medium
type: task
tags:
  - pr:217
---


Add Sqitch migration 008: ALTER TABLE tasks ADD COLUMN pause_metadata JSONB. Store x-asya-pause header content (prompt, fields schema) for clients to render input UI.
