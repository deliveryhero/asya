---
name: obsidian-sync
description: Use when syncing Obsidian vault notes with current project state - updates todos, closes questions, fixes outdated info based on RFCs and beads
---

# Obsidian Vault Synchronization

## Overview

Keep personal Obsidian notes synchronized with the current project state (RFCs in `docs/rfc/`, beads in `.beads/`). Apply minimal, surgical changes to notes.

**Announce at start:** "I'm using the obsidian-sync skill to update your Obsidian notes based on current project state."

## Configuration

The vault path is configured in `.claude/settings.local.json`:

```json
{
  "env": {
    "OBSIDIAN_VAULT_PATH": "/path/to/your/obsidian-vault"
  }
}
```

**First step:** Read the vault path from settings:
```bash
# The path is available as $OBSIDIAN_VAULT_PATH environment variable
echo $OBSIDIAN_VAULT_PATH
```

If `OBSIDIAN_VAULT_PATH` is not set, ask the user to configure it.

## First Step: Read Vault's AGENTS.md

Before making any changes, read the vault's own guidance:

```bash
cat $OBSIDIAN_VAULT_PATH/AGENTS.md
```

This file documents:
- Vault structure and folder organization
- Naming conventions for notes
- Tags and content patterns
- Guidelines for updating notes (preserve voice, minimal changes, etc.)

**Always follow the vault's AGENTS.md guidelines.**

## Workflow

### Phase 1: Gather Current Project State

1. **Check recent beads** for completed/in-progress work:
   ```bash
   bd list --status=closed | head -20   # Recently completed
   bd list --status=open | head -20     # Current work
   ```

2. **Check RFCs** for architectural decisions:
   ```bash
   ls docs/rfc/
   ```

3. **Check recent commits** for implemented features:
   ```bash
   git log --oneline -20
   ```

### Phase 2: Find Relevant Obsidian Notes

Search for notes related to the current work:

```bash
# Search by topic
grep -rl "topic-keyword" $OBSIDIAN_VAULT_PATH/ --include="*.md"

# List Asya-related notes
ls $OBSIDIAN_VAULT_PATH/Asya*.md

# Search for specific patterns
grep -l "TODO\|FIXME\|WIP\|open question" $OBSIDIAN_VAULT_PATH/*.md
```

### Phase 3: Apply Minimal Updates

Follow the guidelines from the vault's `AGENTS.md`. Key principles:
- Make the smallest change that updates the note accurately
- Preserve the note's structure and voice
- Add dates to completed items: `[x] Done (2025-01)` or `~~strikethrough~~`

**Common update patterns:**

1. **Mark completed items:**
   ```diff
   - [ ] Implement envelope tracking
   + [x] Implement envelope tracking (done in asya-24)
   ```

2. **Close open questions:**
   ```diff
   - **Open question:** Should we use RabbitMQ or SQS?
   + **Resolved:** Using both - pluggable transport layer (see RFC asya-bi7)
   ```

3. **Update outdated info:**
   ```diff
   - Current status: POC phase
   + Current status: Alpha - operator and gateway working
   ```

4. **Add cross-references:**
   ```diff
   + See also: docs/rfc/asya-bi8-agentic-asya.md
   ```

### Phase 4: Commit Changes

After updating notes, commit to the obsidian repo:

```bash
cd $OBSIDIAN_VAULT_PATH

# Check changes
git status
git diff

# Commit with descriptive message
git add -A
git commit -m "sync: update notes based on asya project progress

- Mark completed: [list items]
- Close questions: [list items]
- Update status: [list items]"

# Push to remote
git push
```

## Examples

### Example 1: After closing a bead

```bash
# Bead asya-12 "Implement happy-end actor" was closed
# Find related obsidian note
grep -l "happy-end\|crew actors" $OBSIDIAN_VAULT_PATH/*.md

# Update the note
# - Mark the TODO as done
# - Add reference to the implementation
```

### Example 2: After merging an RFC

```bash
# RFC asya-bi8 was merged
# Find notes discussing this topic
grep -l "agentic\|multi-agent" $OBSIDIAN_VAULT_PATH/*.md

# Update the notes
# - Close open questions about approach
# - Add link to RFC
# - Update status from "idea" to "implemented"
```

### Example 3: Regular sync session

```bash
# 1. Get recent project changes
bd list --status=closed --since=7d
git log --oneline --since="7 days ago"

# 2. For each completed item, search obsidian
grep -l "keyword" $OBSIDIAN_VAULT_PATH/*.md

# 3. Update matching notes
# 4. Commit all changes together
```

## Safety

- Always `git diff` before committing to review changes
- Keep commits atomic - one logical update per commit if possible
- Use descriptive commit messages referencing what was synced
