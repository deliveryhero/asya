---
title: Update existing flow examples and tests for new compiler pipeline
priority: 2 # medium
dependencies:
  - o8ql
---


Update all existing flow examples in examples/flows/ and their compiled/ outputs to work with the new compiler pipeline. Re-run compilation, verify graph outputs match expected topology. Update unit tests for parser, codegen. Add unit tests for analyzer (_extract_yield_edges, merge algorithm, three handler categories) and graphgen (DOT, Mermaid, JSON renderers). Verify edge cases: single-actor flow, multiple exitpoints, nested if/while, fanout.
