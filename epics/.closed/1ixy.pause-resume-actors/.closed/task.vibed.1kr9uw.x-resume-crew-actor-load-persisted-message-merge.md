---
title: "x-resume crew actor: load persisted message, merge input, continue route"
priority: 2 # medium
type: task
tags:
  - pr:221
dependencies:
  - 1ixy/1kjvyj
---



Implement x-resume handler in src/asya-crew. Read x-asya-resume-task header to find task ID. Load persisted message from S3. Merge user input into restored payload using pause metadata field mappings (payload_key paths with / notation). Configurable shallow/deep merge via env var (shallow default). Restore route via VFS route/next. Read x-asya-resume-timeout header, stamp new deadline_at on outbound message. Unit tests.
