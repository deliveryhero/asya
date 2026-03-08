---
title: "Inline comment overrides for compiler rules (# asya: <action>)"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/support-more-compiler-constructs/pyn3.inline-comment-overrides-compiler-rules-asya-treat-as
  - branch:support-more-compiler-constructs/pyn3.inline-comment-overrides-compiler-rules-asya-treat-as
  - pr:278
  - pr:280
---




## Problem

The flow compiler does not parse inline comments. Python's AST module strips
comments, so `# asya: actor` annotations are completely invisible to the
compiler. There is no way to override compiler rules at the call site.

## Design

Inline comments provide the highest-priority override mechanism for compiler
rules. Syntax follows standard Python tool conventions (`# type: ignore`,
`# noqa: E501`, `# pragma: no cover`): short prefix + action word.

```python
p = handler(p)              # asya: actor
p = handler(p)              # asya: inline
p["id"] = str(uuid4())      # asya: inline
p = sub_pipeline(p)         # asya: flow
p = handler(p)              # asya: unfold
```

No infrastructure parameters (actor names, config values) in inline comments.
Flow definitions stay pure business logic. Actor naming, configuration, and
deployment details are managed in manifests via CLI/UI.

Priority order (highest to lowest):
1. Inline comment (`# asya: <action>`)
2. Matching compiler rule from `asya.yaml`
3. Default (unfold for same-package, inline for external)

### Comment syntax

Pattern: `# asya: <action>` where action is one of:
`actor`, `flow`, `inline`, `unfold`, `config`

The comment must appear on the same line as the statement it annotates.

### Implementation

**Parser** (`src/asya-cli/asya_cli/flow/parser.py`):

The parser already has `self.source_code`. Add comment extraction:

1. Split source into lines at init time
2. For each parsed statement, check `self.source_lines[stmt.lineno - 1]`
   for `# asya:` pattern
3. Parse the directive: extract the action word
4. Store in a dict: `lineno -> AsyaDirective`

```python
@dataclass
class AsyaDirective:
    action: str          # actor, flow, inline, unfold, config

def _extract_directives(self) -> dict[int, AsyaDirective]:
    directives = {}
    for i, line in enumerate(self.source_lines, 1):
        match = re.search(r'#\s*asya:\s*(\w+)', line)
        if match:
            directives[i] = AsyaDirective(action=match.group(1))
    return directives
```

5. In `_parse_actor_call()` and `_parse_assign()`, check for directive at
   the statement's line number before applying default resolution

**IR** (`src/asya-cli/asya_cli/flow/ir.py`):

Extend relevant IR operations with optional override:
```python
@dataclass
class ActorCall(IROperation):
    name: str
    directive: AsyaDirective | None = None
```

**Grouper/Codegen**: Check `directive` field when deciding how to handle
an operation (actor boundary vs inline vs unfold).

### Testing

- Unit: parse `p = handler(p)  # asya: actor` → ActorCall
- Unit: parse `p = handler(p)  # asya: inline` → Mutation
- Unit: comment without `# asya:` prefix → ignored
- Unit: directive on non-call statement → error or ignored
- Unit: directive overrides matching compiler rule
- Unit: unknown action word → FlowCompileError

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for the
full rules resolution priority design.
