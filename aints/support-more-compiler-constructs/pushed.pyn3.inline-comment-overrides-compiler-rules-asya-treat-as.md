---
title: "Inline comment overrides for compiler rules (# asya: treat-as-*)"
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
comments, so `# asya: treat-as-actor` annotations are completely invisible
to the compiler. There is no way to override compiler rules at the call site.

## Design

Inline comments provide the highest-priority override mechanism for compiler
rules. They follow the same `treat-as` vocabulary:

```python
p = handler(p)              # asya: treat-as-actor
p = handler(p)              # asya: treat-as-inline
p["id"] = str(uuid4())      # asya: treat-as-inline
p = sub_pipeline(p)         # asya: treat-as-flow
p = handler(p)              # asya: treat-as-decompose
```

Priority order (highest to lowest):
1. Inline comment (`# asya: treat-as-*`)
2. Matching compiler rule from `asya.yaml`
3. Default (decompose for same-package, inline for external)

### Comment syntax

Pattern: `# asya: treat-as-<action>` where action is one of:
`actor`, `flow`, `inline`, `decompose`, `config`

Optional actor name override: `# asya: treat-as-actor name=order-validator`

The comment must appear on the same line as the statement it annotates.

### Implementation

**Parser** (`src/asya-cli/asya_cli/flow/parser.py`):

The parser already has `self.source_code`. Add comment extraction:

1. Split source into lines at init time
2. For each parsed statement, check `self.source_lines[stmt.lineno - 1]`
   for `# asya:` pattern
3. Parse the directive: `treat-as-<action>` and optional `name=<value>`
4. Store in a dict: `lineno -> AsyaDirective`

```python
@dataclass
class AsyaDirective:
    treat_as: str          # actor, flow, inline, decompose, config
    name: str | None       # optional actor name override

def _extract_directives(self) -> dict[int, AsyaDirective]:
    directives = {}
    for i, line in enumerate(self.source_lines, 1):
        match = re.search(r'#\s*asya:\s*treat-as-(\w+)(?:\s+name=(\S+))?', line)
        if match:
            directives[i] = AsyaDirective(
                treat_as=match.group(1),
                name=match.group(2),
            )
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
an operation (actor boundary vs inline vs decompose).

### Testing

- Unit: parse `p = handler(p)  # asya: treat-as-actor` → ActorCall
- Unit: parse `p = handler(p)  # asya: treat-as-inline` → Mutation
- Unit: parse with `# asya: treat-as-actor name=my-actor` → named actor
- Unit: comment without `# asya:` prefix → ignored
- Unit: directive on non-call statement → error or ignored
- Unit: directive overrides matching compiler rule

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for the
full rules resolution priority design.
