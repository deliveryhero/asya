---
title: "Pre-commit hook doesn't recompile agentic flows (examples/flows/agentic/)"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/support-more-compiler-constructs/36g4.pre-commit-hook-doesn-t-recompile-agentic-flows
  - branch:support-more-compiler-constructs/36g4.pre-commit-hook-doesn-t-recompile-agentic-flows
  - pr:310
---




The compile-flows.sh pre-commit hook compiles examples/flows/*.py but not examples/flows/agentic/*.py. This means agentic flow compiled output (flow.dot, flow.svg, routers.py) is never regenerated, leaving stale artifacts. For example, voting_ensemble/flow.dot still shows list(await asyncio.gather(...)) as inline code instead of fan-out/fan-in nodes because it was compiled before PR #304 fixed the parser.
