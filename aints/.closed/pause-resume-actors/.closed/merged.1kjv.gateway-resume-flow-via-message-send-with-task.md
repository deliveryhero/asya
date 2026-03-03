---
title: "Gateway: resume flow via message/send with task_id"
priority: 2 # medium
tags:
  - pr:217
dependencies:
  - 1ixy/1kmp6r
---


Update A2A handler to detect task_id in message/send params. When task is paused: validate status, extract user input from A2A message parts, create new message with route {curr: x-resume}, set x-asya-resume-task header, queue to x-resume actor, transition task to processing. Unit tests for resume validation, message creation, re-queuing.
