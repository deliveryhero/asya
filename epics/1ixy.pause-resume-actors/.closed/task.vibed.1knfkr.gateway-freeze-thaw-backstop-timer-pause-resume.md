---
title: "Gateway: freeze/thaw backstop timer on pause/resume"
priority: 2 # medium
type: task
tags:
  - pr:217
dependencies:
  - 1ixy/1kmp6r
---


Update taskstore timeout handling: on pause, cancel backstop timer and save remaining_sec (deadline - now). On resume, restart timer with remaining_sec and set x-asya-resume-timeout header on resume message. x-resume uses this to stamp new deadline_at on outbound message. See RFC section 6.3. Unit tests for timer suspend/resume, remaining time calculation.
