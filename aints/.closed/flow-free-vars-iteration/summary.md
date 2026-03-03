---
title: Flow DSL Free Variables and Iteration
reason: won't do for simplicity reasons - in flow, state must be only in payload dict.
priority: 2 # medium
---

Support variables and iteration patterns that cross actor boundaries in the flow DSL compiler. Free variable detection, auto-serialization, for-loop support, and async-for-yield streaming. Supersedes the free-variables portion of closed epic 1c84.handler-signature-redesign.
