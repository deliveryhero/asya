---
title: "x-pause crew actor: persist message and signal pause"
status: merged
priority: 2
parent: hwek2
dependencies:
  - 1kft
  - 1k34
tags:
  - pr:221
---

Implement x-pause handler in src/asya-crew. Verify x-resume is next in route (prepend if missing). Persist full message (payload + route + headers + pause metadata) to S3 via checkpoint handler pattern. Set x-asya-pause header with pause metadata JSON. Return None. Unit tests.
