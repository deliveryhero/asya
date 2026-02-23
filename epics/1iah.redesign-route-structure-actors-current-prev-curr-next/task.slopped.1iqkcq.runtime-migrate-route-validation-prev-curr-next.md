---
title: "Runtime: migrate route validation to prev/curr/next"
priority: 1 # high
type: task
---

Update asya_runtime.py route validation and shift logic from {actors, current} to {prev, curr, next}. Current route increment (route['current'] += 1) becomes shift: prev.append(curr), curr = next[0], next = next[1:]. Update all route-related code paths and unit tests.
