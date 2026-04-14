---
title: "New analyzer.py: yield analysis with _extract_yield_edges and merge algorithm"
status: rejected
priority: 1
dependencies:
  - p2d0
---

New module (~200 lines). Uses ast.parse() to statically analyze handler Python files and extract routing edges from yield ABI patterns. Internal _extract_yield_edges() function classifies yields, extracts targets from string literals/resolve() calls, captures enclosing if/else conditions as edge labels. Three handler categories: generated routers (full), user handlers (best-effort via inspect.getsource), external packages (opaque if no source). Four-step merge: router chains + user overrides + manifest error edges + merge with override:true. Outputs GraphData(nodes, edges, groups). See RFC section: analyzer.py — yield analysis.
