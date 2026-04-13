---
title: "Gateway: resume flow via message/send with task_id"
status: merged
priority: 2
parent: hwek2
dependencies:
  - 1kmp
tags:
  - pr:217
---

Update A2A handler to detect task_id in message/send params. When task is paused: validate status, extract user input from A2A message parts, create new message with route {curr: x-resume}, set x-asya-resume-task header, queue to x-resume actor, transition task to processing. Unit tests for resume validation, message creation, re-queuing.
