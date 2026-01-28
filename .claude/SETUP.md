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

## References

- [beads](https://github.com/steveyegge/beads) - Beads framework
- [obra/superpowers](https://github.com/obra/superpowers) - Agentic skills framework
- [using-git-worktrees skill](https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md) - Complete documentation
- [awesome-claude-skills](https://github.com/VoltAgent/awesome-claude-skills) - 147+ community skills

## Settings

- `settings.json` - Shared Claude Code settings
- `settings.local.json` - Local overrides (not committed)
