---
title: "Gateway: add paused/canceled task statuses and A2A state mapping"
priority: 2 # medium
type: task
---

Add TaskStatusPaused and TaskStatusCanceled to pkg/types/task.go. Add A2AStateCanceled to a2a.go. Update translator.go to map paused->input_required and canceled->canceled. Update IsActive to return false for paused and canceled tasks. Unit tests.
