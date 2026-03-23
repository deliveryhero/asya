---
title: Document skaffold as Python source resolver for compile-time imports
priority: 2 # medium
---

The compiler uses skaffold.yaml artifact context dirs as Python import paths at compile time. This is a key UX feature for bare-script handlers. Needs a docs page covering: how it works, when to use -I/--python-path, the compile-time vs runtime Python impedance mismatch, and the skaffold.yaml as single source of truth for both image names and import paths.
