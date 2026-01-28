# Claude Code Setup for Asya Project

## Git Worktrees for Parallel Agents

Use the **obra/superpowers** plugin instead of custom scripts.

### Installation

In any Claude Code session, run these slash commands:

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

### Available Commands

After installation, use `/help` to see commands:
- `/superpowers:brainstorm` - Interactive design refinement
- `/superpowers:write-plan` - Create implementation plan
- `/superpowers:execute-plan` - Execute plan in batches

The **using-git-worktrees** skill is automatically included.

### Git Worktrees Workflow

The superpowers plugin includes a **using-git-worktrees** skill that:

1. **Creates isolated workspaces** - Automatically sets up worktrees in `.worktrees/` (project-local) or `~/.config/superpowers/worktrees/<project>/` (global)
2. **Verifies safety** - Ensures `.worktrees/` is git-ignored to prevent accidental commits
3. **Runs setup** - Auto-detects project type and runs dependency installation
4. **Tests baseline** - Verifies clean test state before starting work

The skill handles:
- Directory selection and verification
- Project setup (npm install, pip install, cargo build, etc.)
- Baseline test execution
- Safe cleanup

### Manual Worktree Commands

If you prefer direct git commands (`.worktrees/` is already in `.gitignore`):

```bash
# Create worktree in project (recommended)
git worktree add .worktrees/<name> -b worktree/<name>

# List all worktrees
git worktree list

# Remove worktree
git worktree remove .worktrees/<name>
git worktree prune

# Delete branch after removing worktree
git branch -D worktree/<name>
```

## Beads Viewer (bv) - Issue Tracking TUI

The project uses **beads_viewer** for interactive issue tracking. Install and use it to view, create, and manage issues stored in `.beads/`.

### Installation

```bash
curl -fsSL "https://raw.githubusercontent.com/Dicklesworthstone/beads_viewer/main/install.sh?$(date +%s)" | bash
```

### Launch Interactive View

```bash
bv
```

This opens a terminal UI (TUI) where you can:
- Browse all issues with full details
- View dependencies between issues
- Filter by status, type, priority
- See blocking relationships
- Navigate with arrow keys, search with `/`

### CLI Commands (For Agents & Automation)

Use `bd` (CLI) instead of `bv` (TUI) for non-interactive work:

```bash
# List issues
bd list                              # All issues
bd list --status=open                # Only open issues
bd list --status=in_progress         # Only in-progress issues
bd ready                             # Issues ready to work (no blockers)

# View details
bd show <id>                         # Full issue details
bd show <id> --json                  # JSON output

# Create issues
bd create --title="Task description" --type=task --priority=2
# Types: task, bug, feature, epic, question, docs
# Priority: 0-4 (0=critical, 2=medium, 4=backlog)

# Update status
bd update <id> --status=in_progress  # Claim work
bd update <id> --status=completed    # Complete work

# Close issues
bd close <id>                        # Mark complete
bd close <id> --reason="Why"         # With explanation
bd close <id1> <id2>                 # Close multiple at once

# Dependencies
bd dep add <issue> <depends-on>      # Add dependency (issue depends on depends-on)
bd blocked                           # Show all blocked issues

# Sync with git
bd sync                              # Commit and push beads changes
bd sync --status                     # Check sync status without syncing
```

### Workflow Integration

**Start of session**:
```bash
bd ready        # Find actionable tasks
bd show <id>    # Review task details
bd update <id> --status=in_progress
```

**End of session**:
```bash
bd close <id1> <id2>  # Close completed issues
bd sync               # Push changes to remote
```

### Session Checklist

Before ending any session, run:
```bash
git status              # Check what changed
git add <files>         # Stage code changes
bd sync                 # Commit beads changes and push
git commit -m "..."     # Commit code changes
git push                # Push code to remote
```

## References

- [beads](https://github.com/steveyegge/beads) - Beads framework
- [beads_viewer](https://github.com/Dicklesworthstone/beads_viewer) - Interactive issue tracking TUI
- [obra/superpowers](https://github.com/obra/superpowers) - Agentic skills framework
- [using-git-worktrees skill](https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md) - Complete documentation
- [awesome-claude-skills](https://github.com/VoltAgent/awesome-claude-skills) - 147+ community skills

## Settings

- `settings.json` - Shared Claude Code settings
- `settings.local.json` - Local overrides (not committed)
