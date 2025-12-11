# Scene Compiler Control Flow Rules

## Router Code Generation Rules

1. **Conditions first** - All condition checks must appear before any routing actions
2. **No operations after routing** - Once `_next.append()` is called, only more `_next.append()` allowed
3. **Operation grouping** - Group mutations together, conditions together, routing together
4. **Elif as else-if** - Elif must compile to else branch, not separate router
5. **No duplicate routing** - Don't append same target multiple times

## Examples

```python
# Good - conditions first, mutations grouped, routing grouped
if p['type'] == 'A':
    p['mut'] += 1
    p['status'] = 'active'
    _next.append(resolve("handler_a"))
    _next.append(resolve("router_continue"))

# Bad - mutation after routing
if p['type'] == 'A':
    _next.append(resolve("handler_a"))
    p['mut'] += 1  # FORBIDDEN

# Bad - condition after routing
_next.append(resolve("handler"))
if p['type'] == 'B':  # FORBIDDEN
    ...
```
