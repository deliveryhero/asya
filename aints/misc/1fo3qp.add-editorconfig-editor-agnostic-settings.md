---
title: Add .editorconfig for editor-agnostic settings
status: open
priority: 2 # medium
type: task
---


# Add .editorconfig for Editor-Agnostic Settings

## Goal
Create `.editorconfig` file to enforce consistent code formatting across different editors (VS Code, Vim, Neovim, IntelliJ, etc.) without requiring editor-specific configuration.

## Implementation Plan

### 1. File Location
Create: `.editorconfig`

### 2. Core Configuration
```editorconfig
# EditorConfig is awesome: https://EditorConfig.org

# top-most EditorConfig file
root = true

# Unix-style newlines, UTF-8 encoding for all files
[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

# Go files: tabs, 8-space tab width (Go convention)
[*.go]
indent_style = tab
indent_size = 8

# Python files: spaces, 4 spaces per indent
[*.py]
indent_style = space
indent_size = 4

# YAML/TOML: spaces, 2 spaces per indent
[*.{yml,yaml,toml}]
indent_style = space
indent_size = 2

# JSON: spaces, 2 spaces per indent, no trailing commas
[*.json]
indent_style = space
indent_size = 2

# Markdown: spaces, 2 spaces per indent, preserve trailing whitespace
[*.md]
indent_style = space
indent_size = 2
trim_trailing_whitespace = false

# Shell scripts: spaces, 2 spaces per indent
[*.{sh,bash,zsh}]
indent_style = space
indent_size = 2

# Makefile: MUST use tabs (required by make)
[Makefile]
indent_style = tab
indent_size = 4
```

### 3. Key Rules

**Universal**:
- UTF-8 encoding
- Unix newlines (LF, not CRLF)
- Remove trailing whitespace
- Final newline at end of file

**Language-specific**:
- **Go**: Tabs (Go standard)
- **Python**: 4-space indents (PEP 8)
- **YAML/TOML**: 2-space indents (common config style)
- **JSON**: 2-space indents
- **Markdown**: 2-space indents, preserve trailing whitespace (for line breaks)
- **Shell**: 2-space indents
- **Makefile**: Tabs only (make requirement)

### 4. Editor Support
Most modern editors support EditorConfig natively:
- ✅ VS Code (via EditorConfig extension)
- ✅ Vim/Neovim (via editorconfig-vim plugin)
- ✅ IntelliJ IDEA (built-in)
- ✅ Sublime Text (via package)
- ✅ Emacs (via editorconfig-emacs)

Add note to CONTRIBUTING.md:
```markdown
## Editor Configuration

EditorConfig ensures consistent formatting across editors. If your editor
doesn't have built-in support, install the EditorConfig plugin:
- VS Code: [EditorConfig extension](https://marketplace.visualstudio.com/items?itemName=EditorConfig.EditorConfig)
- Vim: [editorconfig-vim](https://github.com/editorconfig/editorconfig-vim)
- Neovim: [editorconfig-nvim](https://github.com/gpanders/editorconfig-nvim)
```

### 5. Integration with Existing Tools

Works with:
- `make lint` (yamlfmt, prettier, shfmt, etc. respect EditorConfig)
- Pre-commit hooks (will catch violations)
- CI linters (GitHub Actions)

### 6. Acceptance Criteria
✓ `.editorconfig` file created with all sections
✓ Covers all file types in codebase (.go, .py, .yml, .json, .md, .sh, Makefile)
✓ Follows EditorConfig standard syntax
✓ Can be parsed by EditorConfig tools
✓ Rules align with AGENTS.md linting standards
✓ Note added to CONTRIBUTING.md about editor support

## Ready to be done
Marked ready when .editorconfig is complete and tested with editor.


---
_Migrated from beads `asya-tzr`_
