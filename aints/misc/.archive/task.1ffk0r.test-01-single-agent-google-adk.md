---
title: "Test 01-single-agent: Google ADK"
status: done
priority: 2 # medium
type: task
---



Verify ADK example runs: install deps, check imports, run with mock or API


---
## Notes

Fixed: Imports now pass. Uses LlmAgent + InMemoryRunner (correct API). Run requires GOOGLE_API_KEY.


---
**Close reason**: Example imports non-existent Session/Runner classes; incompatible with google-adk 1.23.0


---
_Migrated from beads `asya-1r5`_
