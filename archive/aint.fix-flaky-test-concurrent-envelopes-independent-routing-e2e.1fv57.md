---
title: Fix flaky test_concurrent_envelopes_independent_routing_e2e timeout
status: merged
priority: 1
parent: 00000
tags:
  - type:bug
---

Gateway timeout (120s) is too tight for concurrent envelope test under CI pressure. Only 5s buffer between gateway timeout (120s) and test wait (125s). KEDA scale-up + SQS delays can exceed 120s causing gateway-side envelope timeout.


---
**Close reason**: Fixed: added warm-up envelope to absorb KEDA scale-up time. PR #155


---
_Migrated from beads `asya-0kwq`_
