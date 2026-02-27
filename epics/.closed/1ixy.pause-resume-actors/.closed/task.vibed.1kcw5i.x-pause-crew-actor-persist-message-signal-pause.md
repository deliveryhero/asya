---
title: "x-pause crew actor: persist message and signal pause"
priority: 2 # medium
type: task
tags:
  - pr:221
dependencies:
  - 1ixy/1kftbu
  - debt/1k34nz
---



Implement x-pause handler in src/asya-crew. Verify x-resume is next in route (prepend if missing). Persist full message (payload + route + headers + pause metadata) to S3 via checkpoint handler pattern. Set x-asya-pause header with pause metadata JSON. Return None. Unit tests.
