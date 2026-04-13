---
title: Minor code review comments
status: open
priority: 2
---

`def find_git_root` -> git rev parse?
`def _walk_and_resolve` - what it actually does? can we simplify _resolve_relative_paths?
.asya/config.yaml, .asya/config.foo.bar.yaml -> shorter?
asya_lab/ - compiler/ contains compiler rules, but flow/ contains compiler
analyzer: `edge_type = "prepend" if "[:0]" in path_str else "set"` - should we do proper parsing of ".route.next[???]" expression? Or at least warn that it's not supported

analyzer: `if not isinstance(cmd_node, ast.Constant) or cmd_node.value != "SET":` -> what about DEL? tiny corner case


skaffold:
`def _calculate_module_path` - will change
`_find_flow_function()` - must also work for `# asya: flow`
`def _validate_flow_signature`, is `if not func.returns` syntactic or type annotation? what aboud non-annotated `def flow(p):`?
`'yield' is not supported in flow definitions` -> `... Use actor instead`

parser.py: `if isinstance(base, ast.Name) and base.id == "p":` - has no "else" return


analyzer -> yield_analyzer
parser -> flow_parser?