---
title: "Compiler: support # asya: actor directive on imported function definitions"
priority: 2 # medium
---

Currently # asya: actor on a function definition only works for same-file functions. When the function is in another file (e.g. shouter.py imported by greet_flow.py), the parser doesn't see the directive. Workaround: add # asya: actor on the call site. Fix: scan imported function source lines at compile time.
