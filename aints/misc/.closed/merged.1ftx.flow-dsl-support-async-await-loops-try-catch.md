---
title: "Flow DSL: Support async/await, loops, and try-catch"
priority: 2 # medium
tags:
  - type:feature
---





Extend Flow DSL compiler to support additional control flow constructs:

1. **async/await handlers** - Allow handlers to be async functions (without yield/generators for now - coroutine support will come later)
2. **for/while loops** - Support iteration constructs in flow definitions
3. **try-catch blocks** - Support exception handling in flow definitions

This enables more complex flow patterns while maintaining the Flow DSL's simplicity.


---
**Close reason**: Superseded by epic asya-4ozl which decomposes async/await, loops, and try-catch into separate beads


---
_Migrated from beads `asya-ugj`_
