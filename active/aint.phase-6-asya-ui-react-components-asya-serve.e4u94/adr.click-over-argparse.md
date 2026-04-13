# ADR: Use Click for CLI framework (over argparse and Typer)

**Status**: Accepted
**Date**: 2026-03-09
**Context**: asya-lab CLI framework selection (rfc.md, open question #1)

## Decision

Use **Click** as the CLI framework for asya-lab. Replace the current argparse-based
CLI (`src/asya-cli/asya_cli/cli.py`).

## Requirements

The RFC defines a CLI with:
- 6 command groups, some 3 levels deep
- Shared flags: `--context`, `--arg key=value`, `--set key=value`, `--force`
- Output format: `-o json|yaml|wide`
- Verbosity: `-q`, `-v`, `-vv`, `-vvv`
- Command transparency (print commands before execution)
- Colored error output with file:line references
- Lazy loading (heavy imports like the compiler deferred until needed)

## Why Click

1. **Nested subcommands are native**: `@group.group()` / `@group.command()` handles
   any nesting depth. The current argparse code (66 lines for 2 commands) uses
   `parse_known_args` + manual dispatch -- this pattern does not scale to 6 groups.

2. **Lazy command loading**: `click.Group.get_command()` override defers imports.
   `asya context list` should not import the flow compiler.

3. **Testing**: `click.testing.CliRunner` provides isolated invocation with captured
   output. No `sys.argv` mutation, no stdout monkey-patching. Critical for testing
   git-clean guards and error formatting.

4. **Shell completion**: Built-in for bash/zsh/fish. DS users expect tab completion.

5. **Minimal dependency**: One package (~80KB), zero transitive dependencies.

6. **Optional rich output**: `rich-click` (drop-in `import rich_click as click`)
   adds colored help panels without changing any Click code. Can be gated behind
   the `[ui]` extra.

7. **Maturity**: 13 years, Pallets project (Flask ecosystem). Platform engineers
   who audit dependencies will not object.

## Why not argparse

- **Manual dispatch**: Every nesting level requires `add_subparsers` + `parse_known_args`
  + if/elif dispatch. Three levels (`asya compiler-rule add`) means nested boilerplate.
- **No test runner**: Testing requires mocking `sys.argv` and capturing stdout. Fragile.
- **No shell completion**: Requires third-party `argcomplete`.
- **No shared options pattern**: Parent parser inheritance is fragile. Shared flags
  (`--context`, `-v`) must be added to every subparser or use `parse_known_args` hacks.
- **Help formatting**: `RawDescriptionHelpFormatter` is crude. No auto-generated
  group headers.

The current CLI already shows these limitations at only 2 command groups.

## Why not Typer

- **Heavier dependency chain**: Typer pulls in `click` + `rich` + `shellingham` +
  `typing-extensions` (~1.5MB total). The RFC specifies "core has minimal
  dependencies."
- **Magic gets in the way**: Auto-generating commands from function signatures
  breaks down for custom `ParamType` (e.g., `--arg key=value`), lazy group loading,
  and context propagation. These require dropping to raw Click anyway.
- **Wrapper overhead**: Typer is a layer on top of Click. Edge cases require
  understanding both APIs. Simpler to use Click directly.
- **Younger project** (4 years vs Click's 13). Asya targets platform engineers
  who audit dependencies.

Typer's main advantage (type-inferred options via `Annotated`) saves ~5 lines per
command. Not enough to justify the extra dependencies and abstraction layer.

## Consequences

- Add `click>=8.1` to `asya-lab` core dependencies.
- Replace `argparse` dispatch in `cli.py` with Click groups.
- Existing command handlers (`mcp/commands.py`, `flow_cli.py`) keep their internal
  logic; only the argument parsing entry points change.
- `rich-click` is an optional dependency under the `[ui]` extra.
- Shell completion works out of the box after installation.
