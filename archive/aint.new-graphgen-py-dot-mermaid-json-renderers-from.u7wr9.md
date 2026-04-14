---
title: "New graphgen.py: DOT + Mermaid + JSON renderers from GraphData"
status: rejected
priority: 1
dependencies:
  - h6gnt
---

New module (~150 lines) replacing dotgen.py (~782 lines). Three simple renderers consuming GraphData: to_dot(), to_mermaid(), to_json(). Each ~50 lines (node iteration + edge iteration + formatting). graph.json schema: nodes with id/flow_role/label/image/sources, edges with from/to/label/type/override, groups for inline flow expansion. Delete dotgen.py. See RFC sections: graphgen.py, graph.json schema.
