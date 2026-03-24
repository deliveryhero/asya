---
title: "Compiler: context-aware while loop exit (preserve route.next for composability)"
priority: 1 # high
---

Current fix for break/return in while loops uses 'yield SET .route.next []' which clears the entire route. This breaks composability when flows are nested or composed. The compiler should track how many entries the while loop added to route.next and only remove those, preserving any post-loop continuation from outer scopes. Must test with nested while loops, while inside if/else, and flow composition.
