---
title: "Simplify parser.py: 12 IR types to 5 operation types (ActorCall, Mutation, Conditional, Loop, FanOut)"
priority: 1 # high
dependencies:
  - 7179
---


Rewrite parser.py to emit 5 operation types instead of 12 IR node types. Eliminate Break, Continue, Return, Raise, TryExcept, ExceptHandler, WithBlock from the parser output. Try/except extracts to resiliency_rules (depends on aint 7179). Unmatched constructs (try/except, with-block, decorators without rules) produce compile errors. Delete ir.py. Output: ParseResult with operations, actors, resiliency_rules, extracted_configs, ignore_decorators. See RFC sections: Operation types, Unmatched Python constructs, Where eliminated IR types went.
