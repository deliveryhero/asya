---
title: "Rewrite codegen.py: direct code generation without grouper or Router dataclass"
status: rejected
priority: 1
parent: pj0fo
dependencies:
  - qnyz
---

Rewrite codegen.py to walk the 5 operation types and generate router functions directly. No Router dataclass, no grouper. One decision per router invariant (P13): each router function has at most one level of if/else, nested control flow produces chains of routers. Delete grouper.py (~715 lines). Sequential actors between control flow points grouped into single router. See RFC section: codegen.py — operations to Python code.
